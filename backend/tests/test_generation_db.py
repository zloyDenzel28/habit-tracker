"""generate_for_habit и regenerate (§6.1, §8) — ходят в Postgres, поэтому
их идемпотентность (ON CONFLICT DO NOTHING) можно проверить только по-настоящему,
не юнит-тестом. Ни одна из тринадцати находок сессии тестирования эти функции
не затрагивает напрямую — решение по находке 9 чинит heatmap-ручку, а не
генератор, — поэтому здесь только фиксация текущего (правильного) поведения.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.models import Occurrence, OccurrenceStatus
from app.services.constants import GENERATION_HORIZON_DAYS
from app.services.generation import generate_for_habit, regenerate
from app.services.timeutils import combine_local
from tests.factories import make_habit, make_pause, make_user

MOSCOW = ZoneInfo("Europe/Moscow")


async def _occurrences_of(db_session, habit_id):
    rows = (
        await db_session.scalars(
            select(Occurrence).where(Occurrence.habit_id == habit_id).order_by(Occurrence.local_date)
        )
    ).all()
    return rows


async def test_создаёт_occurrences_только_на_дни_расписания(db_session):
    user = await make_user(db_session, timezone_name="Europe/Moscow")
    habit = await make_habit(
        db_session, user, schedule_time=time(8, 0), schedule_days=[1, 3, 5]
    )
    now = datetime(2026, 8, 24, 3, 0, tzinfo=timezone.utc)  # понедельник, 06:00 MSK

    created = await generate_for_habit(db_session, habit, MOSCOW, now=now, horizon_days=6)

    rows = await _occurrences_of(db_session, habit.id)
    assert created == len(rows)
    assert all(row.local_date.isoweekday() in {1, 3, 5} for row in rows)


async def test_не_создаёт_запись_если_время_уже_прошло(db_session):
    user = await make_user(db_session, timezone_name="Europe/Moscow")
    habit = await make_habit(
        db_session, user, schedule_time=time(8, 0), schedule_days=[1, 2, 3, 4, 5, 6, 7]
    )
    now = datetime(2026, 8, 26, 6, 0, tzinfo=timezone.utc)  # 09:00 MSK, сегодняшние 08:00 прошли

    await generate_for_habit(db_session, habit, MOSCOW, now=now, horizon_days=0)

    rows = await _occurrences_of(db_session, habit.id)
    assert rows == []


async def test_пропускает_дни_активной_паузы(db_session):
    user = await make_user(db_session, timezone_name="Europe/Moscow")
    habit = await make_habit(
        db_session, user, schedule_time=time(8, 0), schedule_days=[1, 2, 3, 4, 5, 6, 7]
    )
    today = date(2026, 8, 26)
    now = datetime(2026, 8, 26, 3, 0, tzinfo=timezone.utc)  # 06:00 MSK
    await make_pause(db_session, habit, starts_on=today, ends_on=today + timedelta(days=2))

    await generate_for_habit(db_session, habit, MOSCOW, now=now, horizon_days=3)

    rows = await _occurrences_of(db_session, habit.id)
    covered = {row.local_date for row in rows}
    assert today not in covered
    assert today + timedelta(days=1) not in covered
    assert today + timedelta(days=2) not in covered
    assert today + timedelta(days=3) in covered


async def test_архивная_привычка_ничего_не_создаёт(db_session):
    user = await make_user(db_session, timezone_name="Europe/Moscow")
    habit = await make_habit(db_session, user, is_archived=True)
    now = datetime(2026, 8, 26, 3, 0, tzinfo=timezone.utc)

    created = await generate_for_habit(db_session, habit, MOSCOW, now=now)

    assert created == 0
    assert await _occurrences_of(db_session, habit.id) == []


async def test_повторный_запуск_не_создаёт_дублей(db_session):
    """Инвариант 7: идемпотентность держится на ON CONFLICT DO NOTHING по
    (habit_id, scheduled_at), не на проверке чтением — единственное, что
    юнит-тест без БД проверить не может."""
    user = await make_user(db_session, timezone_name="Europe/Moscow")
    habit = await make_habit(
        db_session, user, schedule_time=time(8, 0), schedule_days=[1, 2, 3, 4, 5, 6, 7]
    )
    now = datetime(2026, 8, 24, 3, 0, tzinfo=timezone.utc)

    first = await generate_for_habit(db_session, habit, MOSCOW, now=now)
    second = await generate_for_habit(db_session, habit, MOSCOW, now=now)

    assert first == GENERATION_HORIZON_DAYS + 1
    assert second == 0
    rows = await _occurrences_of(db_session, habit.id)
    assert len(rows) == first


async def test_regenerate_сохраняет_прошлое_и_пересобирает_будущее(db_session):
    """§8: правка расписания на месте — прошлые/текущие occurrences не трогаем,
    пересобираем только будущие pending."""
    user = await make_user(db_session, timezone_name="Europe/Moscow")
    habit = await make_habit(
        db_session, user, schedule_time=time(8, 0), schedule_days=[1, 2, 3, 4, 5, 6, 7]
    )
    now = datetime(2026, 8, 24, 3, 0, tzinfo=timezone.utc)
    await generate_for_habit(db_session, habit, MOSCOW, now=now)
    past = await _occurrences_of(db_session, habit.id)
    old_times = {row.local_date: row.scheduled_at for row in past}

    habit.schedule_time = time(20, 0)
    await db_session.flush()
    removed, created = await regenerate(db_session, habit, MOSCOW, now=now)

    rows = await _occurrences_of(db_session, habit.id)
    assert removed == len(past)
    assert created == len(rows)
    for row in rows:
        expected = combine_local(row.local_date, time(20, 0), MOSCOW)
        assert row.scheduled_at == expected
        assert row.scheduled_at != old_times[row.local_date]


async def test_regenerate_не_трогает_уже_отправленные_occurrences(db_session):
    user = await make_user(db_session, timezone_name="Europe/Moscow")
    habit = await make_habit(db_session, user, schedule_time=time(8, 0))
    now = datetime(2026, 8, 26, 4, 30, tzinfo=timezone.utc)  # 07:30 MSK, до 08:00
    await generate_for_habit(db_session, habit, MOSCOW, now=now, horizon_days=0)
    [today_occurrence] = await _occurrences_of(db_session, habit.id)
    today_occurrence.status = OccurrenceStatus.notified
    await db_session.flush()

    habit.schedule_time = time(9, 0)
    await db_session.flush()
    await regenerate(db_session, habit, MOSCOW, now=now)

    await db_session.refresh(today_occurrence)
    assert today_occurrence.status is OccurrenceStatus.notified
    assert today_occurrence.scheduled_at == combine_local(
        today_occurrence.local_date, time(8, 0), MOSCOW
    )
