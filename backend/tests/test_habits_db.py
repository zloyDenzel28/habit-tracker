"""Тесты сервисов из app/services/habits.py, ходящих в Postgres (§8).

change_user_timezone, cancel_pause, pause_habit, archive_habit, restore_habit —
ни один не проверялся до этой сессии: все они читают и пишут occurrences,
а 49 существующих тестов сознательно без БД (см. test_transitions.py).

xfail'ы здесь фиксируют РЕШЁННОЕ поведение из docs/requirements.md по итогам
сессии тестирования 26.08.2026 — код его ещё не реализует. Список xfail этого
файла — чек-лист для сессии починки «таймзона и паузы» из HANDOFF.md.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

from app.models import Occurrence, OccurrenceStatus
from app.services.errors import ValidationError
from app.services.habits import (
    archive_habit,
    cancel_pause,
    change_user_timezone,
    pause_habit,
    restore_habit,
)
from app.services.timeutils import combine_local
from tests.factories import make_habit, make_occurrence, make_pause, make_user

MOSCOW = ZoneInfo("Europe/Moscow")
TOKYO = ZoneInfo("Asia/Tokyo")


# --- change_user_timezone --------------------------------------------------


async def test_pending_пересчитывается_под_новую_таймзону(db_session):
    user = await make_user(db_session, timezone_name="Europe/Moscow")
    habit = await make_habit(db_session, user, schedule_time=time(19, 0))
    now = datetime(2026, 8, 26, 5, 0, tzinfo=timezone.utc)  # 08:00 MSK, задолго до занятия
    old_scheduled = combine_local(date(2026, 8, 27), habit.schedule_time, MOSCOW)
    occurrence = await make_occurrence(
        db_session,
        habit,
        local_date=date(2026, 8, 27),
        scheduled_at=old_scheduled,
        current_due_at=old_scheduled,
        status=OccurrenceStatus.pending,
    )

    touched = await change_user_timezone(db_session, user, "Asia/Tokyo", now=now)

    expected = combine_local(date(2026, 8, 27), habit.schedule_time, TOKYO)
    await db_session.refresh(occurrence)
    assert touched == 1
    assert occurrence.scheduled_at == expected
    assert occurrence.current_due_at == expected
    assert user.timezone == "Asia/Tokyo"


async def test_прошедшее_после_переезда_занятие_удаляется(db_session):
    """Находка 3, решение: удалять, а не оставлять — диспетчер иначе пришлёт
    уведомление в ту же секунду. Само удаление — уже правильное поведение,
    в этой сессии проверяется только его закреплённая часть."""
    user = await make_user(db_session, timezone_name="Europe/Moscow")
    habit = await make_habit(db_session, user, schedule_time=time(19, 0))
    now = datetime(2026, 8, 26, 16, 0, tzinfo=timezone.utc)  # ровно 19:00 MSK
    scheduled = combine_local(date(2026, 8, 26), habit.schedule_time, MOSCOW)
    occurrence = await make_occurrence(
        db_session,
        habit,
        local_date=date(2026, 8, 26),
        scheduled_at=scheduled,
        current_due_at=scheduled,
        status=OccurrenceStatus.pending,
    )
    occurrence_id = occurrence.id

    touched = await change_user_timezone(db_session, user, "Asia/Tokyo", now=now)

    remaining = await db_session.scalar(
        select(Occurrence).where(Occurrence.id == occurrence_id)
    )
    assert touched == 0
    assert remaining is None


async def test_notified_snoozed_in_progress_не_трогаются(db_session):
    """§8: процесс уже запущен, сдвигать его на лету нельзя."""
    user = await make_user(db_session, timezone_name="Europe/Moscow")
    habit = await make_habit(db_session, user, schedule_time=time(19, 0))
    now = datetime(2026, 8, 26, 5, 0, tzinfo=timezone.utc)
    scheduled = combine_local(date(2026, 8, 26), habit.schedule_time, MOSCOW)

    live_statuses = [
        OccurrenceStatus.notified,
        OccurrenceStatus.snoozed,
        OccurrenceStatus.in_progress,
    ]
    occurrences = [
        await make_occurrence(
            db_session,
            habit,
            local_date=date(2026, 8, 26),
            scheduled_at=scheduled + timedelta(minutes=i),
            current_due_at=scheduled + timedelta(minutes=i),
            status=status,
        )
        for i, status in enumerate(live_statuses)
    ]

    touched = await change_user_timezone(db_session, user, "Asia/Tokyo", now=now)

    assert touched == 0
    for occurrence, status in zip(occurrences, live_statuses):
        await db_session.refresh(occurrence)
        assert occurrence.status is status
        assert occurrence.scheduled_at == scheduled + timedelta(
            minutes=live_statuses.index(status)
        )


async def test_paused_пересчитывается_вместе_с_pending(db_session):
    user = await make_user(db_session, timezone_name="Europe/Moscow")
    habit = await make_habit(db_session, user, schedule_time=time(7, 30))
    now = datetime(2026, 8, 26, 3, 0, tzinfo=timezone.utc)
    old_scheduled = combine_local(date(2026, 8, 27), habit.schedule_time, MOSCOW)
    occurrence = await make_occurrence(
        db_session,
        habit,
        local_date=date(2026, 8, 27),
        scheduled_at=old_scheduled,
        current_due_at=old_scheduled,
        status=OccurrenceStatus.paused,
    )

    await change_user_timezone(db_session, user, "Asia/Tokyo", now=now)

    expected = combine_local(date(2026, 8, 27), habit.schedule_time, TOKYO)
    await db_session.refresh(occurrence)
    assert occurrence.scheduled_at == expected
    assert occurrence.current_due_at == expected


# --- cancel_pause ------------------------------------------------------------


async def test_снятие_паузы_возвращает_будущие_дни_в_pending(db_session):
    user = await make_user(db_session, timezone_name="Europe/Moscow")
    habit = await make_habit(db_session, user, schedule_time=time(8, 0))
    today = date(2026, 8, 26)
    now = combine_local(today, time(9, 0), MOSCOW)
    pause = await make_pause(
        db_session, habit, starts_on=today - timedelta(days=1), ends_on=today + timedelta(days=5)
    )
    future = await make_occurrence(
        db_session,
        habit,
        local_date=today + timedelta(days=1),
        scheduled_at=combine_local(today + timedelta(days=1), time(8, 0), MOSCOW),
        current_due_at=combine_local(today + timedelta(days=1), time(8, 0), MOSCOW),
        status=OccurrenceStatus.paused,
    )

    await cancel_pause(db_session, pause, habit, MOSCOW, now=now)

    await db_session.refresh(future)
    assert pause.cancelled_at == now
    assert future.status is OccurrenceStatus.pending


async def test_снятие_паузы_не_трогает_прошедшие_дни_паузы(db_session):
    """Прошедшие дни паузы реально были на паузе — переписывать их задним
    числом означало бы сделать их пропущенными."""
    user = await make_user(db_session, timezone_name="Europe/Moscow")
    habit = await make_habit(db_session, user, schedule_time=time(8, 0))
    today = date(2026, 8, 26)
    now = combine_local(today, time(9, 0), MOSCOW)
    pause = await make_pause(
        db_session, habit, starts_on=today - timedelta(days=5), ends_on=today + timedelta(days=5)
    )
    past = await make_occurrence(
        db_session,
        habit,
        local_date=today - timedelta(days=1),
        scheduled_at=combine_local(today - timedelta(days=1), time(8, 0), MOSCOW),
        current_due_at=combine_local(today - timedelta(days=1), time(8, 0), MOSCOW),
        status=OccurrenceStatus.paused,
    )

    await cancel_pause(db_session, pause, habit, MOSCOW, now=now)

    await db_session.refresh(past)
    assert past.status is OccurrenceStatus.paused


async def test_снятие_паузы_досоздаёт_пропущенные_генератором_дни(db_session):
    """Дни, которые генератор пропустил из-за активной паузы, не имеют записи
    вовсе — cancel_pause обязан вызвать генератор, а не только вернуть paused
    обратно в pending."""
    user = await make_user(db_session, timezone_name="Europe/Moscow")
    habit = await make_habit(
        db_session, user, schedule_time=time(8, 0), schedule_days=[1, 2, 3, 4, 5, 6, 7]
    )
    today = date(2026, 8, 26)
    now = combine_local(today, time(7, 0), MOSCOW)  # до 08:00, значит и сегодня ещё впереди
    pause = await make_pause(
        db_session, habit, starts_on=today, ends_on=today + timedelta(days=3)
    )

    await cancel_pause(db_session, pause, habit, MOSCOW, now=now)

    rows = (
        await db_session.scalars(
            select(Occurrence).where(
                Occurrence.habit_id == habit.id, Occurrence.local_date == today
            )
        )
    ).all()
    assert len(rows) == 1
    assert rows[0].status is OccurrenceStatus.pending


# --- pause_habit -------------------------------------------------------------


async def test_пауза_переводит_только_pending_в_окне_в_paused(db_session):
    user = await make_user(db_session, timezone_name="Europe/Moscow")
    habit = await make_habit(db_session, user, schedule_time=time(8, 0))
    today = date(2026, 8, 26)
    now = combine_local(today, time(7, 0), MOSCOW)

    def _at(day: date) -> datetime:
        return combine_local(day, habit.schedule_time, MOSCOW)

    inside_day = today + timedelta(days=1)
    outside_day = today + timedelta(days=30)
    live_day = today + timedelta(days=2)
    inside = await make_occurrence(
        db_session,
        habit,
        local_date=inside_day,
        scheduled_at=_at(inside_day),
        current_due_at=_at(inside_day),
        status=OccurrenceStatus.pending,
    )
    outside = await make_occurrence(
        db_session,
        habit,
        local_date=outside_day,
        scheduled_at=_at(outside_day),
        current_due_at=_at(outside_day),
        status=OccurrenceStatus.pending,
    )
    live = await make_occurrence(
        db_session,
        habit,
        local_date=live_day,
        scheduled_at=_at(live_day),
        current_due_at=_at(live_day),
        status=OccurrenceStatus.notified,
    )

    await pause_habit(
        db_session, habit, starts_on=today, ends_on=today + timedelta(days=7), now=now
    )

    await db_session.refresh(inside)
    await db_session.refresh(outside)
    await db_session.refresh(live)
    assert inside.status is OccurrenceStatus.paused
    assert outside.status is OccurrenceStatus.pending
    assert live.status is OccurrenceStatus.notified


async def test_пауза_без_даты_окончания_ставится_на_неделю(db_session):
    user = await make_user(db_session, timezone_name="Europe/Moscow")
    habit = await make_habit(db_session, user)
    today = date(2026, 8, 26)

    pause = await pause_habit(db_session, habit, starts_on=today)

    assert pause.ends_on == today + timedelta(days=7)


@pytest.mark.xfail(
    reason="находка 8: pause_habit не проверяет, что starts_on не в прошлом — "
    "ретроспективная пауза длиннее 14 дней задним числом обнуляет серию",
    strict=True,
)
async def test_пауза_задним_числом_запрещена(db_session):
    user = await make_user(db_session, timezone_name="Europe/Moscow")
    habit = await make_habit(db_session, user, schedule_time=time(8, 0))
    today = date(2026, 8, 26)
    now = combine_local(today, time(9, 0), MOSCOW)

    with pytest.raises(ValidationError):
        await pause_habit(
            db_session,
            habit,
            starts_on=today - timedelta(days=20),
            ends_on=today - timedelta(days=1),
            now=now,
        )


# --- archive_habit -----------------------------------------------------------


async def test_архивация_удаляет_будущие_pending_и_сохраняет_историю(db_session):
    user = await make_user(db_session, timezone_name="Europe/Moscow")
    habit = await make_habit(db_session, user, schedule_time=time(8, 0))
    now = datetime(2026, 8, 26, 5, 0, tzinfo=timezone.utc)

    future_pending = await make_occurrence(
        db_session,
        habit,
        scheduled_at=now + timedelta(days=1),
        current_due_at=now + timedelta(days=1),
        status=OccurrenceStatus.pending,
    )
    past_done = await make_occurrence(
        db_session,
        habit,
        scheduled_at=now - timedelta(days=1),
        current_due_at=now - timedelta(days=1),
        status=OccurrenceStatus.done,
        finished_at=now - timedelta(days=1),
    )
    future_pending_id = future_pending.id

    await archive_habit(db_session, habit, now=now)

    remaining = await db_session.scalar(
        select(Occurrence).where(Occurrence.id == future_pending_id)
    )
    await db_session.refresh(past_done)
    assert habit.is_archived is True
    assert remaining is None
    assert past_done.status is OccurrenceStatus.done


@pytest.mark.xfail(
    reason="находка 7: archive_habit не закрывает уже отправленные сегодняшние "
    "занятия — диспетчер продолжает слать по ним догоняющие пинги",
    strict=True,
)
async def test_архивация_закрывает_открытые_занятия_сегодняшнего_дня(db_session):
    user = await make_user(db_session, timezone_name="Europe/Moscow")
    habit = await make_habit(db_session, user, schedule_time=time(8, 0))
    now = datetime(2026, 8, 26, 5, 0, tzinfo=timezone.utc)

    notified_today = await make_occurrence(
        db_session,
        habit,
        local_date=date(2026, 8, 26),
        scheduled_at=now - timedelta(hours=1),
        current_due_at=now - timedelta(hours=1),
        status=OccurrenceStatus.notified,
        notified_at=now - timedelta(hours=1),
    )

    await archive_habit(db_session, habit, now=now)

    await db_session.refresh(notified_today)
    assert notified_today.status is OccurrenceStatus.skipped


# --- restore_habit -------------------------------------------------------------


async def test_восстановление_снимает_архив_и_обнуляет_серию(db_session):
    user = await make_user(db_session, timezone_name="Europe/Moscow")
    habit = await make_habit(
        db_session, user, schedule_time=time(8, 0), is_archived=True
    )
    now = datetime(2026, 8, 26, 5, 0, tzinfo=timezone.utc)  # 08:00 MSK

    await restore_habit(db_session, habit, MOSCOW, now=now)

    assert habit.is_archived is False
    assert habit.streak_reset_on == date(2026, 8, 26)


async def test_восстановление_генерирует_новые_occurrences(db_session):
    user = await make_user(db_session, timezone_name="Europe/Moscow")
    habit = await make_habit(
        db_session,
        user,
        schedule_time=time(8, 0),
        schedule_days=[1, 2, 3, 4, 5, 6, 7],
        is_archived=True,
    )
    now = datetime(2026, 8, 26, 3, 0, tzinfo=timezone.utc)  # 06:00 MSK, привычка ещё впереди

    await restore_habit(db_session, habit, MOSCOW, now=now)

    rows = (
        await db_session.scalars(
            select(Occurrence).where(Occurrence.habit_id == habit.id)
        )
    ).all()
    assert len(rows) > 0
    assert all(row.status is OccurrenceStatus.pending for row in rows)
