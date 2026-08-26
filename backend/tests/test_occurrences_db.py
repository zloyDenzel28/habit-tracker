"""close_local_day (§6.3), ходящий в Postgres — массовый UPDATE, не по одному
объекту, поэтому test_transitions.py его проверить не мог.

Обе xfail-находки чинят одну и ту же функцию (см. HANDOFF.md: «6 и 11 правят
одну и ту же функцию, разносить их по разным сессиям не стоит»).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from app.models import Occurrence, OccurrenceStatus
from app.services.occurrences import UNRESOLVED_STATUSES, close_local_day
from tests.factories import make_habit, make_occurrence, make_user

AT = datetime(2026, 8, 26, 0, 0, tzinfo=timezone.utc)
YESTERDAY = date(2026, 8, 25)
TODAY = date(2026, 8, 26)


async def _closed_status(db_session, occurrence: Occurrence) -> OccurrenceStatus:
    await db_session.refresh(occurrence)
    return occurrence.status


async def test_pending_notified_snoozed_за_прошлую_дату_становятся_missed(db_session):
    user = await make_user(db_session)
    habit = await make_habit(db_session, user)
    unresolved = [
        OccurrenceStatus.pending,
        OccurrenceStatus.notified,
        OccurrenceStatus.snoozed,
    ]
    occurrences = [
        await make_occurrence(
            db_session,
            habit,
            local_date=YESTERDAY,
            scheduled_at=AT - timedelta(hours=len(unresolved) - i),
            current_due_at=AT - timedelta(hours=len(unresolved) - i),
            status=status,
        )
        for i, status in enumerate(unresolved)
    ]

    closed = await close_local_day(db_session, user.id, before_local_date=TODAY, at=AT)

    assert closed == len(unresolved)
    for occurrence in occurrences:
        assert await _closed_status(db_session, occurrence) is OccurrenceStatus.missed


async def test_paused_и_терминальные_не_трогаются(db_session):
    user = await make_user(db_session)
    habit = await make_habit(db_session, user)
    untouched_statuses = [
        OccurrenceStatus.paused,
        OccurrenceStatus.done,
        OccurrenceStatus.skipped,
        OccurrenceStatus.missed,
    ]
    occurrences = [
        await make_occurrence(
            db_session,
            habit,
            local_date=YESTERDAY,
            scheduled_at=AT - timedelta(hours=len(untouched_statuses) - i),
            current_due_at=AT - timedelta(hours=len(untouched_statuses) - i),
            status=status,
            finished_at=AT - timedelta(hours=1) if status != OccurrenceStatus.paused else None,
        )
        for i, status in enumerate(untouched_statuses)
    ]

    closed = await close_local_day(db_session, user.id, before_local_date=TODAY, at=AT)

    assert closed == 0
    for occurrence, status in zip(occurrences, untouched_statuses):
        assert await _closed_status(db_session, occurrence) is status


async def test_будущую_дату_не_трогает(db_session):
    """local_date ещё не наступила — джоб про неё вообще не спрашивает."""
    user = await make_user(db_session)
    habit = await make_habit(db_session, user)
    future = await make_occurrence(
        db_session,
        habit,
        local_date=TODAY,
        scheduled_at=AT,
        current_due_at=AT,
        status=OccurrenceStatus.pending,
    )

    closed = await close_local_day(db_session, user.id, before_local_date=TODAY, at=AT)

    assert closed == 0
    assert await _closed_status(db_session, future) is OccurrenceStatus.pending


async def test_повторный_запуск_в_том_же_часу_идемпотентен(db_session):
    """Инвариант 7: второй прогон не находит уже закрытых записей."""
    user = await make_user(db_session)
    habit = await make_habit(db_session, user)
    await make_occurrence(
        db_session,
        habit,
        local_date=YESTERDAY,
        scheduled_at=AT - timedelta(hours=1),
        current_due_at=AT - timedelta(hours=1),
        status=OccurrenceStatus.pending,
    )

    first = await close_local_day(db_session, user.id, before_local_date=TODAY, at=AT)
    second = await close_local_day(db_session, user.id, before_local_date=TODAY, at=AT)

    assert first == 1
    assert second == 0


@pytest.mark.xfail(
    reason="находка 6: close_local_day не смотрит на current_due_at и закрывает "
    "занятие, снуженное за полночь, раньше обещанного кнопкой срока",
    strict=True,
)
async def test_снуз_за_полночь_доживает_до_своего_срока(db_session):
    """local_date всё ещё вчерашний (снуз его не двигает), но current_due_at
    снуз перенёс в новые сутки — закрывать такое занятие рано."""
    user = await make_user(db_session)
    habit = await make_habit(db_session, user)
    due_in_future = AT + timedelta(minutes=5)
    occurrence = await make_occurrence(
        db_session,
        habit,
        local_date=YESTERDAY,
        scheduled_at=AT - timedelta(hours=1),
        current_due_at=due_in_future,
        status=OccurrenceStatus.snoozed,
    )

    closed = await close_local_day(db_session, user.id, before_local_date=TODAY, at=AT)

    assert closed == 0
    assert await _closed_status(db_session, occurrence) is OccurrenceStatus.snoozed


@pytest.mark.xfail(
    reason="находка 11: закрытие дня вешает missed на in_progress, хотя "
    "started_at заполнен — человек отреагировал, и по §11 missed для него "
    "неправильный статус (нужен skipped, как у «Не получилось»)",
    strict=True,
)
async def test_брошенный_in_progress_закрывается_как_skipped(db_session):
    user = await make_user(db_session)
    habit = await make_habit(db_session, user)
    occurrence = await make_occurrence(
        db_session,
        habit,
        local_date=YESTERDAY,
        scheduled_at=AT - timedelta(hours=2),
        current_due_at=AT - timedelta(hours=2),
        status=OccurrenceStatus.in_progress,
        started_at=AT - timedelta(hours=2),
    )

    await close_local_day(db_session, user.id, before_local_date=TODAY, at=AT)

    assert await _closed_status(db_session, occurrence) is OccurrenceStatus.skipped


def test_набор_незавершённых_статусов_соответствует_спеке():
    assert UNRESOLVED_STATUSES == {
        OccurrenceStatus.pending,
        OccurrenceStatus.notified,
        OccurrenceStatus.snoozed,
        OccurrenceStatus.in_progress,
    }
