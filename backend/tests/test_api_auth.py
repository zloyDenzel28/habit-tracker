"""POST /auth/dev-login (§12.4) — дев-вход в обход Telegram Login Widget."""

from __future__ import annotations

import pytest

from app.config import settings
from tests.factories import make_user

pytestmark = pytest.mark.skipif(
    not settings.dev_auth, reason="DEV_AUTH выключен в этом окружении"
)


async def test_дев_вход_отдаёт_токен_на_сид_пользователя(client, db_session):
    if settings.seed_telegram_id is None:
        pytest.skip("SEED_TELEGRAM_ID не задан")
    user = await make_user(db_session, telegram_id=settings.seed_telegram_id)

    response = await client.post("/auth/dev-login")

    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"] == str(user.id)
    assert body["user"]["id"] == str(user.id)


async def test_дев_вход_без_сид_пользователя_404(client):
    if settings.seed_telegram_id is None:
        pytest.skip("SEED_TELEGRAM_ID не задан")
    response = await client.post("/auth/dev-login")
    assert response.status_code == 404
