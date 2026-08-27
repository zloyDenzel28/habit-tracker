"""Четыре джоба из §6 спеки.

Инвариант 4 распространяется и сюда: джоб — такой же тонкий адаптер, как
роутер API и хендлер бота. Ни одного решения о статусах здесь нет, вся логика
уже лежит в services/. Джоб открывает сессию, зовёт сервис, зовёт Notifier
и пишет в лог.

Инвариант 6: все четыре ходят в БД. Таймеров в памяти нет — они не переживают
рестарт контейнера.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import Occurrence, SentMessage, SentMessageKind
from app.notifier import Notifier
from app.services import generation, messages, occurrences, sent_messages
from app.services.messages import Message
from app.services.timeutils import now_utc, resolve_tz

log = logging.getLogger("scheduler.jobs")

# Потолок на размер пачки в одном тике. Нужен не ради нагрузки, а ради
# длительности транзакции: строки блокируются на всё время отправки.
BATCH_LIMIT = 100

SessionFactory = async_sessionmaker
Builder = Callable[[Occurrence, ZoneInfo], Message]


async def _deliver(
    notifier: Notifier,
    session: AsyncSession,
    occurrence: Occurrence,
    build: Builder,
    kind: SentMessageKind,
    *,
    at: datetime,
) -> bool:
    """Собирает сообщение, отдаёт его Notifier и запоминает отправленное.

    True — если ушло. Ошибка отправки не роняет весь тик: остальные записи
    пачки должны обработаться, а эта попробует ещё раз на следующем тике.

    Запись в sent_messages — та самая, по которой сообщение потом гасится
    (находка 2). Текст кладём тот же, что ушёл в чат: пересобирать его
    в момент закрытия нельзя, занятие к тому времени уже другое.
    """
    try:
        tz = resolve_tz(occurrence.user.timezone)
        message = build(occurrence, tz)
        message_id = await notifier.send(occurrence.user, message.text, message.buttons)
    except Exception:
        log.exception("не удалось отправить уведомление по occurrence %s", occurrence.id)
        return False
    if message_id is not None:
        # None отдаёт LogNotifier: строчку в логе гасить нечем и незачем.
        sent_messages.record(
            session,
            occurrence,
            kind=kind,
            message_id=message_id,
            text=message.text,
            at=at,
        )
    return True


async def _close(
    notifier: Notifier, occurrence: Occurrence, sent: SentMessage, *, at: datetime
) -> bool:
    """Гасит одно сообщение: дописывает итог, убирает кнопки, ставит отметку.

    Порядок тот же, что у отправки: сначала правим чат, потом помечаем.
    Наоборот было бы хуже — отметка стояла бы у сообщения, которое так и
    осталось с живыми кнопками, и повторить было бы уже некому.
    """
    try:
        tz = resolve_tz(occurrence.user.timezone)
        text = messages.closed_text(sent.text, occurrence, tz)
        closed = await notifier.close(occurrence.user, sent.message_id, text)
    except Exception:
        log.exception("не удалось погасить сообщение %s", sent.message_id)
        return False
    if closed:
        sent_messages.mark_closed(sent, at=at)
    return closed


async def generate_occurrences(session_factory: SessionFactory) -> int:
    """§6.1: генератор, раз в сутки в 03:00 UTC.

    Идемпотентен за счёт уникального индекса (habit_id, scheduled_at), поэтому
    лишний запуск безопасен.
    """
    async with session_factory() as session, session.begin():
        # Итог пишет в лог сам сервис, дублировать здесь незачем.
        return await generation.generate_all(session)


async def dispatch_notifications(
    session_factory: SessionFactory, notifier: Notifier
) -> tuple[int, int]:
    """§6.2: диспетчер, раз в SCHEDULER_TICK_SECONDS.

    Сначала отправляем, потом ставим отметку — и то и другое внутри одной
    транзакции, пока строки держит FOR UPDATE ... SKIP LOCKED. Порядок именно
    такой: пометить заранее и упасть на отправке означало бы, что человек
    уведомления не увидит вовсе, а occurrence уже считается notified.
    Обратный риск — падение между отправкой и коммитом — даёт повтор на
    следующем тике, что заметно менее неприятно.
    """
    sent = 0
    followups = 0
    superseded = 0
    async with session_factory() as session, session.begin():
        now = now_utc()

        for occurrence in await occurrences.due_for_notification(
            session, now=now, limit=BATCH_LIMIT
        ):
            # Занятие могло попасть сюда после снуза — тогда в чате уже висят
            # сообщения с живыми кнопками от прошлого ожидания. Гасим их до
            # отправки нового и до mark_notified: итог считается от текущего
            # состояния, а оно сейчас snoozed, то есть «Перенесено на 19:05» —
            # ровно то же, что пишет бот на нажатие «+5 мин». После
            # mark_notified статус стал бы notified и итог получился бы
            # бессмысленным. У pending открытых сообщений нет по определению.
            for stale in await sent_messages.open_for_occurrence(session, occurrence.id):
                if await _close(notifier, occurrence, stale, at=now):
                    superseded += 1

            if await _deliver(
                notifier, session, occurrence, messages.reminder,
                SentMessageKind.notification, at=now,
            ):
                occurrences.mark_notified(occurrence, at=now)
                sent += 1

        for occurrence in await occurrences.due_for_followup(
            session, now=now, limit=BATCH_LIMIT
        ):
            # Первое уведомление намеренно оставляем живым: по §5 пинг его
            # не отменяет, кнопки «Начал» и «+5 мин» под ним ещё работают.
            if await _deliver(
                notifier, session, occurrence, messages.followup,
                SentMessageKind.followup, at=now,
            ):
                occurrences.mark_followup_sent(occurrence, at=now)
                followups += 1

    if sent or followups:
        log.info(
            "диспетчер: уведомлений %d, догоняющих пингов %d, погашено вытесненных %d",
            sent,
            followups,
            superseded,
        )
    else:
        # На отладке тик стоит в 5 секунд, и INFO о пустом проходе забьёт лог.
        log.debug("диспетчер: отправлять нечего")
    return sent, followups


async def close_chat_messages(session_factory: SessionFactory, notifier: Notifier) -> int:
    """§6.4: гасит сообщения занятий, дошедших до терминального статуса.

    Находка 2. Занятие можно закрыть из веба или ночным джобом, а сообщение
    с кнопками при этом остаётся в чате и выглядит как «ещё не отвечено».
    Дотянуться до него можно только по message_id из sent_messages.

    Джобом в воркере, а не вызовом из роутера API, хотя соблазн есть: §2
    разделяет — воркер отправляет, бот принимает, — и дёргать Telegram из
    третьего процесса значило бы это разделение сломать. Плюс инвариант 6
    (планировщик опрашивает БД) и инвариант 7 (повтор ничего не портит:
    защищает closed_at). Плата — задержка до одного тика.

    Занятия, закрытые кнопкой в самом чате, сюда обычно не доходят: бот гасит
    сообщение сразу, у него оно в руках. Но второе сообщение того же занятия
    (первое уведомление и догоняющий пинг живут в чате одновременно) закрывает
    именно этот джоб.
    """
    closed = 0
    async with session_factory() as session, session.begin():
        now = now_utc()
        for sent in await sent_messages.due_for_closing(session, limit=BATCH_LIMIT):
            if await _close(notifier, sent.occurrence, sent, at=now):
                closed += 1
    if closed:
        log.info("закрытие сообщений: погашено %d", closed)
    else:
        log.debug("закрытие сообщений: гасить нечего")
    return closed


async def close_days(session_factory: SessionFactory) -> int:
    """§6.3: закрытие дня, ежечасно.

    Ежечасно, потому что полночь наступает в разное время в разных таймзонах.
    Кому именно пора закрывать день, решает сервис.
    """
    async with session_factory() as session, session.begin():
        closed = await occurrences.close_finished_days(session)
    if closed:
        # Не «в missed»: брошенный in_progress уходит в skipped (§6.3).
        log.info("закрытие дня: закрыто занятий %d", closed)
    else:
        log.debug("закрытие дня: незакрытых записей нет")
    return closed
