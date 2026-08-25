"""Жизненный цикл occurrence (§4 спеки) и выборки для планировщика (§6.2).

Инвариант 4: это единственное место, где меняется статус occurrence. API и бот
только вызывают эти функции — одно и то же действие обязано вести себя
одинаково из веба и из Telegram.

Переходы намеренно синхронные и не трогают сессию: они меняют уже загруженный
объект, а решение о commit принимает вызывающий адаптер. Так одно действие
пользователя остаётся одной транзакцией, а логику можно проверять юнит-тестом
без поднятой БД.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import date, datetime

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.models import MAX_SNOOZE_COUNT, TERMINAL_STATUSES, Occurrence, OccurrenceStatus
from app.services.constants import SNOOZE_STEP
from app.services.errors import AlreadyInStatus, InvalidTransition, SnoozeLimitReached
from app.services.timeutils import ensure_aware, now_utc

# Статусы, из которых occurrence ещё может куда-то уйти.
# paused сюда входит: §4 описывает переход paused -> pending при снятии паузы,
# поэтому терминальным он быть не может, несмотря на формулировку в тексте.
OPEN_STATUSES: frozenset[OccurrenceStatus] = frozenset(
    set(OccurrenceStatus) - set(TERMINAL_STATUSES)
)

# Статусы «день начался, но ещё не закрыт» — их подчищает ночной джоб (§6.3).
UNRESOLVED_STATUSES: frozenset[OccurrenceStatus] = frozenset(
    {
        OccurrenceStatus.pending,
        OccurrenceStatus.notified,
        OccurrenceStatus.snoozed,
        OccurrenceStatus.in_progress,
    }
)


def _transition(
    occurrence: Occurrence,
    action: str,
    allowed: frozenset[OccurrenceStatus],
    target: OccurrenceStatus,
) -> None:
    """Проверяет переход и переводит статус. Единственная точка смены status."""
    if occurrence.status is target:
        # Двойное нажатие, а не нарушение жизненного цикла: кнопка под старым
        # сообщением в Telegram остаётся кликабельной сколько угодно долго.
        raise AlreadyInStatus(action, occurrence.status, allowed)
    if occurrence.status not in allowed:
        raise InvalidTransition(action, occurrence.status, allowed)
    occurrence.status = target


# --- переходы -------------------------------------------------------------

NOTIFY_FROM = frozenset({OccurrenceStatus.pending, OccurrenceStatus.snoozed})
SNOOZE_FROM = frozenset({OccurrenceStatus.notified})
START_FROM = frozenset({OccurrenceStatus.notified, OccurrenceStatus.snoozed})
COMPLETE_FROM = frozenset(
    {OccurrenceStatus.in_progress, OccurrenceStatus.notified, OccurrenceStatus.snoozed}
)
SKIP_FROM = frozenset(
    {OccurrenceStatus.notified, OccurrenceStatus.snoozed, OccurrenceStatus.in_progress}
)
PAUSE_FROM = frozenset({OccurrenceStatus.pending})
RESUME_FROM = frozenset({OccurrenceStatus.paused})


def mark_notified(occurrence: Occurrence, *, at: datetime | None = None) -> Occurrence:
    """Планировщик отправил уведомление: pending/snoozed -> notified."""
    at = ensure_aware(at) if at else now_utc()
    _transition(occurrence, "notify", NOTIFY_FROM, OccurrenceStatus.notified)
    occurrence.notified_at = at
    return occurrence


def snooze(occurrence: Occurrence, *, at: datetime | None = None) -> Occurrence:
    """Кнопка «+5 мин»: notified -> snoozed.

    Считаем от максимума из планового времени и «сейчас». По букве §4 это
    current_due_at += 5, но если человек отреагировал на уведомление через
    двадцать минут, то +5 к старому времени даёт момент в прошлом — и следующий
    же тик планировщика пришлёт напоминание мгновенно. Кнопка обещает
    «через пять минут», её и выполняем.
    """
    at = ensure_aware(at) if at else now_utc()
    if occurrence.snooze_count >= MAX_SNOOZE_COUNT:
        # §4: на шестой раз кнопка уже не показывается, но проверка нужна —
        # старое сообщение в чате про это не знает.
        raise SnoozeLimitReached(MAX_SNOOZE_COUNT)
    _transition(occurrence, "snooze", SNOOZE_FROM, OccurrenceStatus.snoozed)
    occurrence.current_due_at = max(occurrence.current_due_at, at) + SNOOZE_STEP
    occurrence.snooze_count += 1
    # Снуз переносит выполнение, поэтому уже отправленный догоняющий пинг
    # больше не актуален: разрешаем прислать новый от нового current_due_at.
    occurrence.followup_sent_at = None
    return occurrence


def can_snooze(occurrence: Occurrence) -> bool:
    """§4: показывать ли кнопку «+5 мин»."""
    return occurrence.status in SNOOZE_FROM and occurrence.snooze_count < MAX_SNOOZE_COUNT


def start(occurrence: Occurrence, *, at: datetime | None = None) -> Occurrence:
    """Кнопка «Начал»: notified/snoozed -> in_progress.

    started_at пишем от нажатия, а не от планового времени: таймер догоняющего
    пинга должен идти от момента, когда человек реально начал.
    """
    at = ensure_aware(at) if at else now_utc()
    _transition(occurrence, "start", START_FROM, OccurrenceStatus.in_progress)
    occurrence.started_at = at
    return occurrence


def complete(occurrence: Occurrence, *, at: datetime | None = None) -> Occurrence:
    """Кнопка «Выполнил» -> done.

    Разрешено не только из in_progress: §5 показывает «Выполнил» и на
    догоняющем пинге для того, кто на первое уведомление не отреагировал,
    а такой occurrence всё ещё в статусе notified. started_at при этом
    остаётся пустым — человек не нажимал «Начал», и выдумывать время начала
    мы не будем.
    """
    at = ensure_aware(at) if at else now_utc()
    _transition(occurrence, "complete", COMPLETE_FROM, OccurrenceStatus.done)
    occurrence.finished_at = at
    return occurrence


def skip(occurrence: Occurrence, *, at: datetime | None = None) -> Occurrence:
    """Кнопки «Пропустить сегодня» и «Не получилось» -> skipped.

    Из in_progress тоже: §5 даёт кнопку «Не получилось» тому, кто начал,
    но не закончил. Это осознанный ответ пользователя, поэтому skipped,
    а не missed — missed означает «не отреагировал вовсе» (§11).
    """
    at = ensure_aware(at) if at else now_utc()
    _transition(occurrence, "skip", SKIP_FROM, OccurrenceStatus.skipped)
    occurrence.finished_at = at
    return occurrence


def mark_missed(occurrence: Occurrence, *, at: datetime | None = None) -> Occurrence:
    """Ночной джоб закрывает день: всё неотвеченное -> missed.

    paused сюда не попадает: приостановленный день не пропущен, он просто
    не участвует в расчётах (§7).
    """
    at = ensure_aware(at) if at else now_utc()
    _transition(occurrence, "miss", UNRESOLVED_STATUSES, OccurrenceStatus.missed)
    occurrence.finished_at = at
    return occurrence


def mark_followup_sent(occurrence: Occurrence, *, at: datetime | None = None) -> Occurrence:
    """Отметка об отправке догоняющего пинга. Статус не меняет.

    Инвариант 7: повторно не перезаписываем — иначе перезапуск джоба
    отправит пинг второй раз.
    """
    at = ensure_aware(at) if at else now_utc()
    if occurrence.followup_sent_at is None:
        occurrence.followup_sent_at = at
    return occurrence


def pause_occurrence(occurrence: Occurrence) -> Occurrence:
    """pending -> paused при постановке привычки на паузу."""
    _transition(occurrence, "pause", PAUSE_FROM, OccurrenceStatus.paused)
    return occurrence


def resume_occurrence(occurrence: Occurrence) -> Occurrence:
    """paused -> pending при снятии паузы (§4, «если время ещё не прошло»)."""
    _transition(occurrence, "resume", RESUME_FROM, OccurrenceStatus.pending)
    return occurrence


# --- выборки --------------------------------------------------------------


async def due_for_notification(
    session: AsyncSession, *, now: datetime | None = None, limit: int | None = None
) -> Sequence[Occurrence]:
    """§6.2: кому пора отправить первое уведомление.

    FOR UPDATE ... SKIP LOCKED — страховка на случай, если воркер когда-нибудь
    запустят в двух экземплярах: второй просто не увидит уже разбираемые строки
    и не продублирует уведомление. Блокируем только occurrences (of=), habit
    и user нужны на чтение.
    """
    now = ensure_aware(now) if now else now_utc()
    stmt = (
        select(Occurrence)
        .where(
            Occurrence.status.in_([OccurrenceStatus.pending, OccurrenceStatus.snoozed]),
            Occurrence.current_due_at <= now,
        )
        .order_by(Occurrence.current_due_at)
        .options(
            joinedload(Occurrence.habit, innerjoin=True),
            joinedload(Occurrence.user, innerjoin=True),
        )
        .with_for_update(skip_locked=True, of=Occurrence)
    )
    if limit is not None:
        stmt = stmt.limit(limit)
    return (await session.scalars(stmt)).all()


def _elapsed_at(anchor, minutes_column):
    """anchor + duration_minutes, посчитанное на стороне Postgres."""
    # make_interval(years, months, weeks, days, hours, mins, secs) — шестой
    # позиционный аргумент это минуты.
    return anchor + func.make_interval(0, 0, 0, 0, 0, minutes_column)


async def due_for_followup(
    session: AsyncSession, *, now: datetime | None = None, limit: int | None = None
) -> Sequence[Occurrence]:
    """§6.2: кому пора отправить догоняющий пинг «Выполнил?».

    Два случая из §5: человек нажал «Начал» — считаем от started_at; человек
    не отреагировал — считаем от current_due_at, поэтому снуз двигает пинг
    автоматически. followup_sent_at IS NULL защищает от повтора (инвариант 7).
    """
    now = ensure_aware(now) if now else now_utc()
    stmt = (
        select(Occurrence)
        .where(
            Occurrence.followup_sent_at.is_(None),
            or_(
                (Occurrence.status == OccurrenceStatus.in_progress)
                & (_elapsed_at(Occurrence.started_at, Occurrence.duration_minutes) <= now),
                (Occurrence.status == OccurrenceStatus.notified)
                & (_elapsed_at(Occurrence.current_due_at, Occurrence.duration_minutes) <= now),
            ),
        )
        .order_by(Occurrence.current_due_at)
        .options(
            joinedload(Occurrence.habit, innerjoin=True),
            joinedload(Occurrence.user, innerjoin=True),
        )
        .with_for_update(skip_locked=True, of=Occurrence)
    )
    if limit is not None:
        stmt = stmt.limit(limit)
    return (await session.scalars(stmt)).all()


async def close_local_day(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    before_local_date: date,
    at: datetime | None = None,
) -> int:
    """§6.3: у пользователя наступила полночь — закрываем всё прошлое как missed.

    Массовым UPDATE, а не по одному объекту: за раз может закрываться много дней,
    а решение принимает WHERE, а не бизнес-правило. Условие по статусам
    повторяет mark_missed: paused не трогаем.
    """
    at = ensure_aware(at) if at else now_utc()
    result = await session.execute(
        update(Occurrence)
        .where(
            Occurrence.user_id == user_id,
            Occurrence.local_date < before_local_date,
            Occurrence.status.in_(UNRESOLVED_STATUSES),
        )
        .values(status=OccurrenceStatus.missed, finished_at=at)
        .execution_options(synchronize_session=False)
    )
    return result.rowcount or 0


async def get_for_user(
    session: AsyncSession, occurrence_id: uuid.UUID, user_id: uuid.UUID
) -> Occurrence | None:
    """Загрузка одной записи вместе с привычкой.

    user_id в условии, а не только id: иначе подделанный callback_data позволит
    боту дёрнуть чужой occurrence.
    """
    return await session.scalar(
        select(Occurrence)
        .where(Occurrence.id == occurrence_id, Occurrence.user_id == user_id)
        .options(joinedload(Occurrence.habit, innerjoin=True))
    )


async def list_for_local_date(
    session: AsyncSession, user_id: uuid.UUID, day: date
) -> Sequence[Occurrence]:
    """Экран «Сегодня» (§9)."""
    return (
        await session.scalars(
            select(Occurrence)
            .where(Occurrence.user_id == user_id, Occurrence.local_date == day)
            .order_by(Occurrence.current_due_at)
            .options(joinedload(Occurrence.habit, innerjoin=True))
        )
    ).all()
