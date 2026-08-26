"""Три джоба из §6 спеки.

Инвариант 4 распространяется и сюда: джоб — такой же тонкий адаптер, как
роутер API и хендлер бота. Ни одного решения о статусах здесь нет, вся логика
уже лежит в services/. Джоб открывает сессию, зовёт сервис, зовёт Notifier
и пишет в лог.

Инвариант 6: все три ходят в БД. Таймеров в памяти нет — они не переживают
рестарт контейнера.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import async_sessionmaker

from app.models import Occurrence
from app.notifier import Notifier
from app.services import generation, messages, occurrences
from app.services.messages import Message
from app.services.timeutils import now_utc, resolve_tz

log = logging.getLogger("scheduler.jobs")

# Потолок на размер пачки в одном тике. Нужен не ради нагрузки, а ради
# длительности транзакции: строки блокируются на всё время отправки.
BATCH_LIMIT = 100

SessionFactory = async_sessionmaker
Builder = Callable[[Occurrence, ZoneInfo], Message]


async def _deliver(notifier: Notifier, occurrence: Occurrence, build: Builder) -> bool:
    """Собирает сообщение и отдаёт его Notifier. True — если ушло.

    Ошибка отправки не роняет весь тик: остальные записи пачки должны
    обработаться, а эта попробует ещё раз на следующем тике.
    """
    try:
        tz = resolve_tz(occurrence.user.timezone)
        message = build(occurrence, tz)
        await notifier.send(occurrence.user, message.text, message.buttons)
    except Exception:
        log.exception("не удалось отправить уведомление по occurrence %s", occurrence.id)
        return False
    return True


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
    async with session_factory() as session, session.begin():
        now = now_utc()

        for occurrence in await occurrences.due_for_notification(
            session, now=now, limit=BATCH_LIMIT
        ):
            if await _deliver(notifier, occurrence, messages.reminder):
                occurrences.mark_notified(occurrence, at=now)
                sent += 1

        for occurrence in await occurrences.due_for_followup(
            session, now=now, limit=BATCH_LIMIT
        ):
            if await _deliver(notifier, occurrence, messages.followup):
                occurrences.mark_followup_sent(occurrence, at=now)
                followups += 1

    if sent or followups:
        log.info("диспетчер: уведомлений %d, догоняющих пингов %d", sent, followups)
    else:
        # На отладке тик стоит в 5 секунд, и INFO о пустом проходе забьёт лог.
        log.debug("диспетчер: отправлять нечего")
    return sent, followups


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
