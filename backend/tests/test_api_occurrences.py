"""/occurrences/*: экран «Сегодня» (§9) — коды ответов, доступ к чужой записи,
превращение доменных ошибок в HTTP (общий обработчик в app/api/main.py)."""

from __future__ import annotations

from datetime import datetime, timezone

from app.models import OccurrenceStatus
from app.services.timeutils import local_date_of, now_utc, resolve_tz
from tests.conftest import auth_headers
from tests.factories import make_habit, make_occurrence, make_user

NOW = datetime(2026, 8, 26, 16, 0, tzinfo=timezone.utc)


async def test_список_на_сегодня_по_умолчанию(client, db_session):
    """Роутер берёт local_date из реального «сейчас» (user_today), а не из
    аргумента — поэтому и occurrence в тесте датируется настоящим сегодня
    по таймзоне пользователя, а не фиксированной датой."""
    user = await make_user(db_session, timezone_name="Europe/Moscow")
    habit = await make_habit(db_session, user)
    real_now = now_utc()
    today_local = local_date_of(real_now, resolve_tz(user.timezone))
    today = await make_occurrence(
        db_session, habit, local_date=today_local, scheduled_at=real_now
    )

    response = await client.get("/occurrences", headers=auth_headers(user))

    assert response.status_code == 200
    ids = [row["id"] for row in response.json()]
    assert str(today.id) in ids


async def test_start_меняет_статус(client, db_session):
    user = await make_user(db_session)
    habit = await make_habit(db_session, user)
    occurrence = await make_occurrence(
        db_session, habit, status=OccurrenceStatus.notified, notified_at=NOW
    )

    response = await client.post(
        f"/occurrences/{occurrence.id}/start", headers=auth_headers(user)
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "in_progress"
    assert body["started_at"] is not None


async def test_недопустимый_переход_409(client, db_session):
    user = await make_user(db_session)
    habit = await make_habit(db_session, user)
    occurrence = await make_occurrence(db_session, habit, status=OccurrenceStatus.pending)

    response = await client.post(
        f"/occurrences/{occurrence.id}/start", headers=auth_headers(user)
    )

    assert response.status_code == 409
    assert "detail" in response.json()


async def test_повторное_нажатие_тоже_409(client, db_session):
    """AlreadyInStatus — подкласс InvalidTransition, оба маппятся в 409."""
    user = await make_user(db_session)
    habit = await make_habit(db_session, user)
    occurrence = await make_occurrence(
        db_session,
        habit,
        status=OccurrenceStatus.done,
        finished_at=NOW,
    )

    response = await client.post(
        f"/occurrences/{occurrence.id}/complete", headers=auth_headers(user)
    )

    assert response.status_code == 409


async def test_снуз_исчерпан_409(client, db_session):
    user = await make_user(db_session)
    habit = await make_habit(db_session, user)
    occurrence = await make_occurrence(
        db_session, habit, status=OccurrenceStatus.notified, snooze_count=5
    )

    response = await client.post(
        f"/occurrences/{occurrence.id}/snooze", headers=auth_headers(user)
    )

    assert response.status_code == 409


async def test_несуществующее_занятие_404(client, db_session):
    user = await make_user(db_session)
    response = await client.post(
        "/occurrences/00000000-0000-0000-0000-000000000000/skip",
        headers=auth_headers(user),
    )
    assert response.status_code == 404


async def test_чужое_занятие_404(client, db_session):
    owner = await make_user(db_session, telegram_id=1)
    intruder = await make_user(db_session, telegram_id=2)
    habit = await make_habit(db_session, owner)
    occurrence = await make_occurrence(db_session, habit, status=OccurrenceStatus.notified)

    response = await client.post(
        f"/occurrences/{occurrence.id}/skip", headers=auth_headers(intruder)
    )

    assert response.status_code == 404


async def test_без_токена_401(client, db_session):
    user = await make_user(db_session)
    habit = await make_habit(db_session, user)
    occurrence = await make_occurrence(db_session, habit)

    response = await client.post(f"/occurrences/{occurrence.id}/skip")

    assert response.status_code == 401
