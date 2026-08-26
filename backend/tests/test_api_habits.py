"""/habits/*: экраны «Мои привычки» и «Привычка» (§9) — коды ответов, доступ
к чужому ресурсу, превращение доменных ошибок в HTTP."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

from app.models import OccurrenceStatus
from tests.conftest import auth_headers
from tests.factories import make_habit, make_occurrence, make_pause, make_user


async def test_создание_привычки_201(client, db_session):
    user = await make_user(db_session)

    response = await client.post(
        "/habits",
        json={
            "title": "Планка",
            "duration_minutes": 5,
            "schedule_days": [1, 3, 5],
            "schedule_time": "08:05:00",
        },
        headers=auth_headers(user),
    )

    assert response.status_code == 201
    body = response.json()
    assert body["title"] == "Планка"
    assert body["is_archived"] is False


async def test_пустое_название_400(client, db_session):
    user = await make_user(db_session)

    response = await client.post(
        "/habits",
        json={
            "title": "   ",
            "duration_minutes": 5,
            "schedule_days": [1],
            "schedule_time": "08:00:00",
        },
        headers=auth_headers(user),
    )

    assert response.status_code == 400


async def test_слишком_короткая_длительность_400(client, db_session):
    user = await make_user(db_session)

    response = await client.post(
        "/habits",
        json={
            "title": "Слишком быстро",
            "duration_minutes": 1,
            "schedule_days": [1],
            "schedule_time": "08:00:00",
        },
        headers=auth_headers(user),
    )

    assert response.status_code == 400


async def test_чужая_привычка_404_на_всех_ручках(client, db_session):
    owner = await make_user(db_session, telegram_id=11)
    intruder = await make_user(db_session, telegram_id=12)
    habit = await make_habit(db_session, owner)
    headers = auth_headers(intruder)

    get_resp = await client.get(f"/habits/{habit.id}", headers=headers)
    patch_resp = await client.patch(
        f"/habits/{habit.id}", json={"title": "Чужое"}, headers=headers
    )
    archive_resp = await client.post(f"/habits/{habit.id}/archive", headers=headers)
    stats_resp = await client.get(f"/habits/{habit.id}/stats", headers=headers)
    heatmap_resp = await client.get(f"/habits/{habit.id}/heatmap", headers=headers)
    pauses_resp = await client.get(f"/habits/{habit.id}/pauses", headers=headers)

    for response in (
        get_resp,
        patch_resp,
        archive_resp,
        stats_resp,
        heatmap_resp,
        pauses_resp,
    ):
        assert response.status_code == 404


async def test_несуществующая_привычка_404(client, db_session):
    user = await make_user(db_session)
    response = await client.get(
        "/habits/00000000-0000-0000-0000-000000000000", headers=auth_headers(user)
    )
    assert response.status_code == 404


async def test_архивация_и_восстановление(client, db_session):
    user = await make_user(db_session)
    habit = await make_habit(db_session, user)
    headers = auth_headers(user)

    archive_resp = await client.post(f"/habits/{habit.id}/archive", headers=headers)
    assert archive_resp.status_code == 200
    assert archive_resp.json()["is_archived"] is True

    restore_resp = await client.post(f"/habits/{habit.id}/restore", headers=headers)
    assert restore_resp.status_code == 200
    assert restore_resp.json()["is_archived"] is False


async def test_создание_паузы_201_и_список(client, db_session):
    user = await make_user(db_session)
    habit = await make_habit(db_session, user)
    headers = auth_headers(user)
    today = date.today()

    create_resp = await client.post(
        f"/habits/{habit.id}/pauses",
        json={"starts_on": today.isoformat(), "ends_on": (today + timedelta(days=3)).isoformat()},
        headers=headers,
    )
    assert create_resp.status_code == 201

    list_resp = await client.get(f"/habits/{habit.id}/pauses", headers=headers)
    assert list_resp.status_code == 200
    assert len(list_resp.json()) == 1


async def test_дата_окончания_паузы_раньше_начала_400(client, db_session):
    user = await make_user(db_session)
    habit = await make_habit(db_session, user)
    today = date.today()

    response = await client.post(
        f"/habits/{habit.id}/pauses",
        json={
            "starts_on": today.isoformat(),
            "ends_on": (today - timedelta(days=1)).isoformat(),
        },
        headers=auth_headers(user),
    )

    assert response.status_code == 400


async def test_снятие_паузы_чужого_habit_id_404(client, db_session):
    """pause_id существует, но принадлежит другой привычке — тоже 404,
    не 200 и не 500: подделанный маршрут не должен трогать чужую запись."""
    user = await make_user(db_session)
    habit_a = await make_habit(db_session, user, title="A")
    habit_b = await make_habit(db_session, user, title="B")
    pause = await make_pause(
        db_session, habit_a, starts_on=date.today(), ends_on=date.today() + timedelta(days=3)
    )

    response = await client.post(
        f"/habits/{habit_b.id}/pauses/{pause.id}/cancel", headers=auth_headers(user)
    )

    assert response.status_code == 404


async def test_предпросмотр_паузы_дольше_14_дней(client, db_session):
    user = await make_user(db_session)
    habit = await make_habit(db_session, user)
    today = date.today()

    response = await client.get(
        f"/habits/{habit.id}/pause-preview",
        params={
            "starts_on": today.isoformat(),
            "ends_on": (today + timedelta(days=20)).isoformat(),
        },
        headers=auth_headers(user),
    )

    assert response.status_code == 200
    assert response.json()["resets_streak"] is True


async def test_проверка_пересечений(client, db_session):
    user = await make_user(db_session)

    await make_habit(
        db_session,
        user,
        title="Тренировка",
        schedule_days=[1, 2, 3],
        schedule_time=time(19, 30),
        duration_minutes=30,
    )

    response = await client.post(
        "/habits/check-overlap",
        json={
            "schedule_days": [1],
            "schedule_time": "19:45:00",
            "duration_minutes": 15,
        },
        headers=auth_headers(user),
    )

    assert response.status_code == 200
    titles = [row["title"] for row in response.json()]
    assert "Тренировка" in titles


async def test_heatmap_красит_все_дни_длинной_паузы(client, db_session):
    user = await make_user(db_session)
    habit = await make_habit(db_session, user)
    today = date.today()
    pause_end = today + timedelta(days=19)
    await make_pause(db_session, habit, starts_on=today, ends_on=pause_end)
    # Горизонт генерации — только двое суток, поэтому «руками» создаём ровно
    # то, что реально появится в БД к моменту запроса heatmap.
    base = datetime(2026, 1, 1, 8, 0, tzinfo=timezone.utc)
    for offset in range(2):
        day = today + timedelta(days=offset)
        await make_occurrence(
            db_session,
            habit,
            local_date=day,
            scheduled_at=base + timedelta(days=offset),
            status=OccurrenceStatus.paused,
        )

    response = await client.get(
        f"/habits/{habit.id}/heatmap",
        params={"start": today.isoformat(), "end": pause_end.isoformat()},
        headers=auth_headers(user),
    )

    assert response.status_code == 200
    paused_days = {row["date"] for row in response.json() if row["status"] == "paused"}
    assert len(paused_days) == 20
