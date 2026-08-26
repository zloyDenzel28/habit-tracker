"""Хелперы для наполнения тестовой БД в тестах сервисного слоя и роутеров.

Не test_*-модуль — pytest его не собирает как набор тестов, только импортирует.
Пишут строки напрямую через ORM, а не через services.habits.create_habit:
это тесты сервисного слоя, и генерация occurrences здесь не всегда нужна
или должна управляться самим тестом.
"""

from __future__ import annotations

import itertools
from datetime import date, datetime, time, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Habit, HabitPause, Occurrence, OccurrenceStatus, User

_telegram_id_seq = itertools.count(900_000_000_001)

DEFAULT_SCHEDULED_AT = datetime(2026, 8, 26, 8, 0, tzinfo=timezone.utc)


async def make_user(
    session: AsyncSession, *, timezone_name: str = "Europe/Moscow", **overrides
) -> User:
    defaults = dict(
        telegram_id=next(_telegram_id_seq),
        telegram_username="tester",
        first_name="Тест",
        timezone=timezone_name,
    )
    defaults.update(overrides)
    user = User(**defaults)
    session.add(user)
    await session.flush()
    return user


async def make_habit(session: AsyncSession, user: User, **overrides) -> Habit:
    defaults = dict(
        user_id=user.id,
        title="Привычка",
        description=None,
        duration_minutes=15,
        schedule_days=[1, 2, 3, 4, 5, 6, 7],
        schedule_time=time(8, 0),
        is_archived=False,
    )
    defaults.update(overrides)
    habit = Habit(**defaults)
    session.add(habit)
    await session.flush()
    return habit


async def make_occurrence(session: AsyncSession, habit: Habit, **overrides) -> Occurrence:
    scheduled_at = overrides.pop("scheduled_at", DEFAULT_SCHEDULED_AT)
    defaults = dict(
        habit_id=habit.id,
        user_id=habit.user_id,
        local_date=overrides.pop("local_date", scheduled_at.date()),
        scheduled_at=scheduled_at,
        current_due_at=overrides.pop("current_due_at", scheduled_at),
        duration_minutes=habit.duration_minutes,
        status=OccurrenceStatus.pending,
    )
    defaults.update(overrides)
    occurrence = Occurrence(**defaults)
    session.add(occurrence)
    await session.flush()
    return occurrence


async def make_pause(
    session: AsyncSession, habit: Habit, *, starts_on: date, ends_on: date, **overrides
) -> HabitPause:
    pause = HabitPause(habit_id=habit.id, starts_on=starts_on, ends_on=ends_on, **overrides)
    session.add(pause)
    await session.flush()
    return pause
