"""Генерация occurrences по расписанию привычки (§6.1).

Здесь только правило «какие occurrences должны существовать». Когда именно
запускать генератор — дело планировщика (шаг 3); он вызовет generate_all.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.models import Habit, Occurrence, OccurrenceStatus
from app.services.constants import GENERATION_HORIZON_DAYS
from app.services.pauses import is_paused_on, load_pause_windows
from app.services.timeutils import (
    combine_local,
    days_range,
    ensure_aware,
    local_date_of,
    now_utc,
    resolve_tz,
)

log = logging.getLogger(__name__)


async def generate_for_habit(
    session: AsyncSession,
    habit: Habit,
    tz: ZoneInfo,
    *,
    now: datetime | None = None,
    horizon_days: int = GENERATION_HORIZON_DAYS,
) -> int:
    """Создаёт недостающие occurrences привычки на сегодня и horizon_days вперёд.

    Возвращает число реально созданных записей.

    Идемпотентность (инвариант 7) держится не на проверке «а есть ли уже такой»,
    а на ON CONFLICT DO NOTHING по уникальному индексу (habit_id, scheduled_at).
    Проверка чтением здесь не годится: между SELECT и INSERT влезет второй
    запуск джоба и создаст дубль.
    """
    now = ensure_aware(now) if now else now_utc()
    if habit.is_archived:
        # §8: за время архива occurrences не генерируются.
        return 0

    today = local_date_of(now, tz)
    windows = await load_pause_windows(session, habit.id, tz)
    schedule_days = set(habit.schedule_days)

    rows = []
    for day in days_range(today, today + timedelta(days=horizon_days)):
        if day.isoweekday() not in schedule_days:
            continue
        if is_paused_on(windows, day):
            # §6.1: дни активной паузы пропускаем. Записи со статусом paused
            # создаёт постановка на паузу, а не генератор.
            continue
        scheduled_at = combine_local(day, habit.schedule_time, tz)
        if scheduled_at <= now:
            # Время уже прошло. Создавать такую запись нельзя: диспетчер увидит
            # current_due_at <= now и мгновенно пришлёт уведомление о том,
            # что должно было случиться утром.
            continue
        rows.append(
            {
                "habit_id": habit.id,
                "user_id": habit.user_id,
                "local_date": day,
                "scheduled_at": scheduled_at,
                "current_due_at": scheduled_at,
                # Снимок длительности: правка привычки не должна задним числом
                # менять таймер уже созданных occurrences (поправка к §3).
                "duration_minutes": habit.duration_minutes,
                "status": OccurrenceStatus.pending,
            }
        )

    if not rows:
        return 0

    result = await session.execute(
        pg_insert(Occurrence)
        .values(rows)
        .on_conflict_do_nothing(index_elements=["habit_id", "scheduled_at"])
        .returning(Occurrence.id)
    )
    return len(result.scalars().all())


async def generate_all(
    session: AsyncSession,
    *,
    now: datetime | None = None,
    horizon_days: int = GENERATION_HORIZON_DAYS,
) -> int:
    """Прогон генератора по всем активным привычкам всех пользователей."""
    now = ensure_aware(now) if now else now_utc()
    habits: Sequence[Habit] = (
        await session.scalars(
            select(Habit)
            .where(Habit.is_archived.is_(False))
            .options(joinedload(Habit.user, innerjoin=True))
        )
    ).all()

    created = 0
    for habit in habits:
        tz = resolve_tz(habit.user.timezone)
        created += await generate_for_habit(
            session, habit, tz, now=now, horizon_days=horizon_days
        )
    log.info("генератор: привычек %d, создано occurrences %d", len(habits), created)
    return created


async def delete_future_pending(
    session: AsyncSession, habit: Habit, *, now: datetime | None = None
) -> int:
    """Удаляет ещё не наступившие pending-записи привычки (§8).

    Только pending и только будущие: notified, snoozed и in_progress трогать
    нельзя — процесс уже пошёл, а история по §8 неприкосновенна.
    """
    now = ensure_aware(now) if now else now_utc()
    result = await session.execute(
        delete(Occurrence).where(
            Occurrence.habit_id == habit.id,
            Occurrence.status == OccurrenceStatus.pending,
            Occurrence.scheduled_at > now,
        )
    )
    return result.rowcount or 0


async def regenerate(
    session: AsyncSession,
    habit: Habit,
    tz: ZoneInfo,
    *,
    now: datetime | None = None,
) -> tuple[int, int]:
    """Пересборка будущего расписания привычки: снести pending и создать заново.

    Возвращает (удалено, создано).
    """
    now = ensure_aware(now) if now else now_utc()
    removed = await delete_future_pending(session, habit, now=now)
    # flush обязателен: без него INSERT уйдёт в БД раньше DELETE и словит
    # конфликт по (habit_id, scheduled_at) на записи, которую мы только что
    # пометили на удаление.
    await session.flush()
    created = await generate_for_habit(session, habit, tz, now=now)
    return removed, created
