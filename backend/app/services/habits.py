"""Операции над привычкой: создание, правка, архив, пауза, смена таймзоны.

Всё, что меняет расписание, обязано после себя пересобрать будущие occurrences —
иначе привычка и её план разъедутся. Поэтому regenerate вызывается здесь,
а не оставляется на совесть вызывающего кода.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Sequence
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.models import Habit, HabitPause, Occurrence, OccurrenceStatus, User
from app.services.constants import (
    DEFAULT_DURATION_MINUTES,
    DEFAULT_PAUSE_DAYS,
    MIN_DURATION_MINUTES,
    PAUSE_STREAK_RESET_DAYS,
    WEEKDAYS,
)
from app.services.errors import ValidationError
from app.services.generation import delete_future_pending, generate_for_habit, regenerate
from app.services.timeutils import (
    combine_local,
    ensure_aware,
    local_date_of,
    now_utc,
    resolve_tz,
)

_UNSET = object()


# --- валидация ------------------------------------------------------------


def normalize_schedule_days(days: Iterable[int]) -> list[int]:
    """Дни недели 1-7 (пн-вс), без дублей и по порядку."""
    result = sorted({int(day) for day in days})
    if not result:
        raise ValidationError("расписание должно содержать хотя бы один день недели")
    if not set(result) <= WEEKDAYS:
        raise ValidationError("дни недели задаются числами 1-7 (пн-вс)")
    return result


def normalize_duration(minutes: int) -> int:
    """§3: минимум 5 минут. Ограничение снизу убирает класс «привычек
    без длительности», на которых догоняющий пинг теряет смысл."""
    minutes = int(minutes)
    if minutes < MIN_DURATION_MINUTES:
        raise ValidationError(f"длительность не меньше {MIN_DURATION_MINUTES} минут")
    return minutes


def normalize_title(title: str) -> str:
    cleaned = title.strip()
    if not cleaned:
        raise ValidationError("название привычки не может быть пустым")
    return cleaned


# --- создание и правка ----------------------------------------------------


async def create_habit(
    session: AsyncSession,
    user: User,
    *,
    title: str,
    schedule_days: Iterable[int],
    schedule_time: time,
    duration_minutes: int = DEFAULT_DURATION_MINUTES,
    description: str | None = None,
    now: datetime | None = None,
) -> Habit:
    """Заводит привычку и сразу создаёт её occurrences на горизонт генерации.

    Без немедленной генерации привычка, созданная днём, начнёт напоминать только
    после ночного джоба — то есть завтра.
    """
    now = ensure_aware(now) if now else now_utc()
    tz = resolve_tz(user.timezone)

    habit = Habit(
        user_id=user.id,
        title=normalize_title(title),
        description=description,
        duration_minutes=normalize_duration(duration_minutes),
        schedule_days=normalize_schedule_days(schedule_days),
        schedule_time=schedule_time,
        is_archived=False,
    )
    session.add(habit)
    # flush, а не commit: нужен сгенерированный id для occurrences, но
    # границу транзакции определяет вызывающий адаптер.
    await session.flush()

    await generate_for_habit(session, habit, tz, now=now)
    return habit


async def update_habit(
    session: AsyncSession,
    habit: Habit,
    tz: ZoneInfo,
    *,
    title: str | None = None,
    description: object = _UNSET,
    duration_minutes: int | None = None,
    schedule_days: Iterable[int] | None = None,
    schedule_time: time | None = None,
    now: datetime | None = None,
) -> Habit:
    """§8: правка на месте, без версионирования.

    Прошлые и текущие occurrences не трогаются — история должна остаться
    достоверной. Пересобираются только будущие pending. Новая длительность
    попадёт только в новые записи: у существующих duration_minutes — снимок.

    description принимает None как значение («стереть описание»), поэтому
    отличается от «не передано» через _UNSET, а не через None.
    """
    now = ensure_aware(now) if now else now_utc()

    if title is not None:
        habit.title = normalize_title(title)
    if description is not _UNSET:
        habit.description = description  # type: ignore[assignment]
    if duration_minutes is not None:
        habit.duration_minutes = normalize_duration(duration_minutes)
    if schedule_days is not None:
        habit.schedule_days = normalize_schedule_days(schedule_days)
    if schedule_time is not None:
        habit.schedule_time = schedule_time

    await session.flush()
    await regenerate(session, habit, tz, now=now)
    return habit


async def archive_habit(
    session: AsyncSession, habit: Habit, *, now: datetime | None = None
) -> Habit:
    """§8: мягкое удаление. История сохраняется, будущие pending исчезают.

    HabitPause здесь не создаётся (инвариант 8): архивация — это отказ
    от привычки, а не перерыв в ней.
    """
    now = ensure_aware(now) if now else now_utc()
    habit.is_archived = True
    await session.flush()
    await delete_future_pending(session, habit, now=now)
    return habit


async def restore_habit(
    session: AsyncSession, habit: Habit, tz: ZoneInfo, *, now: datetime | None = None
) -> Habit:
    """§8: восстановление из архива обнуляет текущую серию, рекорд остаётся.

    Без этого архив работал бы как бесконечная пауза в обход правила 14 дней:
    за время архива occurrences не создаются, значит в расчёте серии этих дней
    просто нет, и старая серия продолжилась бы как ни в чём не бывало.
    Отметку ставим датой восстановления — с неё серия считается заново.
    """
    now = ensure_aware(now) if now else now_utc()
    habit.is_archived = False
    habit.streak_reset_on = local_date_of(now, tz)
    await session.flush()
    await generate_for_habit(session, habit, tz, now=now)
    return habit


# --- паузы ----------------------------------------------------------------


def pause_resets_streak(starts_on: date, ends_on: date) -> bool:
    """§7: подскажет форме заморозки, показывать ли предупреждение
    «пауза дольше 14 дней обнулит текущую серию»."""
    return (ends_on - starts_on).days + 1 > PAUSE_STREAK_RESET_DAYS


async def pause_habit(
    session: AsyncSession,
    habit: Habit,
    *,
    starts_on: date,
    ends_on: date | None = None,
    now: datetime | None = None,
) -> HabitPause:
    """Ставит привычку на паузу и переводит попавшие в интервал pending в paused.

    Инвариант 8: вызывается только из явного действия пользователя.
    """
    now = ensure_aware(now) if now else now_utc()
    if ends_on is None:
        # §3: дата окончания обязательна, по умолчанию неделя. Бессрочная пауза
        # даёт мёртвые привычки с формально живым стриком.
        ends_on = starts_on + timedelta(days=DEFAULT_PAUSE_DAYS)
    if ends_on < starts_on:
        raise ValidationError("дата окончания паузы раньше даты начала")

    pause = HabitPause(habit_id=habit.id, starts_on=starts_on, ends_on=ends_on)
    session.add(pause)
    await session.flush()

    # Только pending: notified, snoozed и in_progress уже в работе, обрывать их
    # паузой нельзя — уведомление человек уже получил.
    await session.execute(
        update(Occurrence)
        .where(
            Occurrence.habit_id == habit.id,
            Occurrence.status == OccurrenceStatus.pending,
            Occurrence.local_date >= starts_on,
            Occurrence.local_date <= ends_on,
        )
        .values(status=OccurrenceStatus.paused)
        .execution_options(synchronize_session=False)
    )
    return pause


async def cancel_pause(
    session: AsyncSession,
    pause: HabitPause,
    habit: Habit,
    tz: ZoneInfo,
    *,
    now: datetime | None = None,
) -> HabitPause:
    """Досрочное снятие паузы: paused -> pending для дней, которые ещё впереди.

    Прошедшие дни паузы остаются paused: они действительно были на паузе,
    и переписывать их означало бы задним числом сделать их пропущенными.
    """
    now = ensure_aware(now) if now else now_utc()
    if pause.cancelled_at is None:
        pause.cancelled_at = now
    today = local_date_of(now, tz)

    await session.execute(
        update(Occurrence)
        .where(
            Occurrence.habit_id == habit.id,
            Occurrence.status == OccurrenceStatus.paused,
            Occurrence.local_date >= today,
        )
        .values(status=OccurrenceStatus.pending)
        .execution_options(synchronize_session=False)
    )
    await session.flush()
    # Дни, которые генератор пропустил из-за паузы, надо досоздать.
    await generate_for_habit(session, habit, tz, now=now)
    return pause


async def active_pauses(session: AsyncSession, habit_id: uuid.UUID) -> Sequence[HabitPause]:
    """Незакрытые паузы привычки — для экрана привычки и для кнопки «снять»."""
    return (
        await session.scalars(
            select(HabitPause)
            .where(HabitPause.habit_id == habit_id, HabitPause.cancelled_at.is_(None))
            .order_by(HabitPause.starts_on)
        )
    ).all()


# --- таймзона пользователя ------------------------------------------------


async def change_user_timezone(
    session: AsyncSession, user: User, timezone_name: str, *, now: datetime | None = None
) -> int:
    """§8: пересобирает pending occurrences под новую таймзону.

    Пересчитываются только pending. notified, snoozed и in_progress не трогаем:
    процесс уже запущен, сдвиг на лету означал бы либо второе уведомление,
    либо потерянный таймер. Терминальные записи неизменны — local_date
    фиксирует день, в который событие реально произошло.

    Возвращает число пересчитанных записей.
    """
    now = ensure_aware(now) if now else now_utc()
    tz = resolve_tz(timezone_name)
    user.timezone = timezone_name

    pending = (
        await session.scalars(
            select(Occurrence)
            .where(
                Occurrence.user_id == user.id,
                Occurrence.status == OccurrenceStatus.pending,
            )
            .options(joinedload(Occurrence.habit, innerjoin=True))
        )
    ).all()

    touched = 0
    for occurrence in pending:
        scheduled_at = combine_local(
            occurrence.local_date, occurrence.habit.schedule_time, tz
        )
        if scheduled_at <= now:
            # После переезда плановое время этого дня уже прошло. Оставить —
            # значит получить уведомление в ту же секунду; удаляем по тому же
            # правилу, по которому генератор не создаёт записи в прошлом.
            await session.delete(occurrence)
            continue
        occurrence.scheduled_at = scheduled_at
        # У pending снузов не бывает: снуз возможен только из notified.
        occurrence.current_due_at = scheduled_at
        touched += 1

    await session.flush()
    return touched


# --- проверка пересечений (§9) --------------------------------------------


def _window(start: time, duration_minutes: int) -> tuple[int, int]:
    """Окно привычки в минутах от полуночи: [начало, конец)."""
    start_minutes = start.hour * 60 + start.minute
    return start_minutes, start_minutes + duration_minutes


async def find_overlaps(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    schedule_days: Iterable[int],
    schedule_time: time,
    duration_minutes: int,
    exclude_habit_id: uuid.UUID | None = None,
) -> list[Habit]:
    """§9: активные привычки, чьё окно пересекается с проверяемым.

    Пересечение только подсвечивается, сохранение не блокирует (§11), поэтому
    считаем грубо и в питоне: активных привычек у человека единицы.
    Снузы не учитываем — они непредсказуемы на этапе создания (§11).
    Окно, переходящее за полночь, в соседние сутки не переносим: привычка
    длиной в несколько часов ночью — не тот случай, ради которого стоит
    усложнять предупреждение.
    """
    days = set(normalize_schedule_days(schedule_days))
    start, end = _window(schedule_time, normalize_duration(duration_minutes))

    candidates = (
        await session.scalars(
            select(Habit).where(
                Habit.user_id == user_id,
                Habit.is_archived.is_(False),
            )
        )
    ).all()

    overlaps = []
    for habit in candidates:
        if exclude_habit_id is not None and habit.id == exclude_habit_id:
            continue
        if not days & set(habit.schedule_days):
            continue
        other_start, other_end = _window(habit.schedule_time, habit.duration_minutes)
        if start < other_end and other_start < end:
            overlaps.append(habit)
    return overlaps


async def habits_of_user(
    session: AsyncSession, user_id: uuid.UUID, *, include_archived: bool = False
) -> Sequence[Habit]:
    stmt = select(Habit).where(Habit.user_id == user_id)
    if not include_archived:
        stmt = stmt.where(Habit.is_archived.is_(False))
    return (await session.scalars(stmt.order_by(Habit.schedule_time, Habit.title))).all()


def user_today(user: User, *, now: datetime | None = None) -> date:
    """Сегодняшняя дата глазами пользователя."""
    now = ensure_aware(now) if now else now_utc()
    return local_date_of(now, resolve_tz(user.timezone))
