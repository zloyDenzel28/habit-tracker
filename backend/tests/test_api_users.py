"""GET/PATCH /users/me (§9 «Настройки»): профиль и смена таймзоны."""

from __future__ import annotations

from datetime import date, time

import pytest

from app.models import OccurrenceStatus
from app.services.timeutils import combine_local
from tests.conftest import auth_headers
from tests.factories import make_habit, make_occurrence, make_user
from zoneinfo import ZoneInfo

MOSCOW = ZoneInfo("Europe/Moscow")


async def test_без_токена_401(client):
    response = await client.get("/users/me")
    assert response.status_code == 401


async def test_с_битым_токеном_401(client):
    response = await client.get("/users/me", headers={"Authorization": "Bearer not-a-uuid"})
    assert response.status_code == 401


async def test_с_чужим_несуществующим_токеном_401(client):
    response = await client.get(
        "/users/me",
        headers={"Authorization": "Bearer 00000000-0000-0000-0000-000000000000"},
    )
    assert response.status_code == 401


async def test_получить_профиль(client, db_session):
    user = await make_user(db_session, timezone_name="Europe/Moscow")

    response = await client.get("/users/me", headers=auth_headers(user))

    assert response.status_code == 200
    assert response.json()["timezone"] == "Europe/Moscow"


async def test_смена_таймзоны_пересчитывает_pending(client, db_session):
    user = await make_user(db_session, timezone_name="Europe/Moscow")
    habit = await make_habit(db_session, user, schedule_time=time(19, 0))
    scheduled = combine_local(date(2026, 9, 1), habit.schedule_time, MOSCOW)
    occurrence = await make_occurrence(
        db_session,
        habit,
        local_date=date(2026, 9, 1),
        scheduled_at=scheduled,
        current_due_at=scheduled,
        status=OccurrenceStatus.pending,
    )

    response = await client.patch(
        "/users/me", json={"timezone": "Asia/Tokyo"}, headers=auth_headers(user)
    )

    assert response.status_code == 200
    assert response.json()["timezone"] == "Asia/Tokyo"
    expected = combine_local(date(2026, 9, 1), habit.schedule_time, ZoneInfo("Asia/Tokyo"))
    await db_session.refresh(occurrence)
    assert occurrence.scheduled_at == expected


async def test_неизвестная_таймзона_400(client, db_session):
    user = await make_user(db_session)

    response = await client.patch(
        "/users/me", json={"timezone": "Mars/Phobos"}, headers=auth_headers(user)
    )

    assert response.status_code == 400


async def test_сошедшиеся_занятия_дают_409_а_не_500(client, db_session):
    """Находка 5: два занятия на один день с разным scheduled_at пересчёт
    сводит к одному моменту и упирается в уникальный индекс. Причину дублей
    сняла находка 4, но старые пары могли остаться в БД, и человек не должен
    видеть голый 500 — уникальность здесь бизнес-правило, а не сбой."""
    user = await make_user(db_session, timezone_name="Europe/Moscow")
    habit = await make_habit(db_session, user, schedule_time=time(7, 30))
    day = date(2026, 9, 1)
    for scheduled in (
        combine_local(day, habit.schedule_time, MOSCOW),
        combine_local(day, habit.schedule_time, ZoneInfo("Asia/Tokyo")),
    ):
        await make_occurrence(
            db_session,
            habit,
            local_date=day,
            scheduled_at=scheduled,
            current_due_at=scheduled,
            status=OccurrenceStatus.pending,
        )

    response = await client.patch(
        "/users/me", json={"timezone": "Asia/Tokyo"}, headers=auth_headers(user)
    )

    assert response.status_code == 409


async def test_предпросмотр_смены_таймзоны_показывает_число_удаляемых_занятий(
    client, db_session
):
    user = await make_user(db_session, timezone_name="Europe/Moscow")
    habit = await make_habit(db_session, user, schedule_time=time(19, 0))
    scheduled = combine_local(date(2026, 8, 26), habit.schedule_time, MOSCOW)
    await make_occurrence(
        db_session,
        habit,
        local_date=date(2026, 8, 26),
        scheduled_at=scheduled,
        current_due_at=scheduled,
        status=OccurrenceStatus.pending,
    )

    response = await client.get(
        "/users/timezone-preview",
        params={"timezone": "Asia/Tokyo"},
        headers=auth_headers(user),
    )

    assert response.status_code == 200
    assert response.json()["removed_today"] == 1
