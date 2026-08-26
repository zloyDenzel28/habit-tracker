"""POST /auth/dev-login — §12.4: обход Telegram Login Widget на localhost."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from app.api.deps import SessionDep
from app.api.schemas import DevLoginOut, user_out
from app.config import settings
from app.services import users

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/dev-login", response_model=DevLoginOut)
async def dev_login(session: SessionDep) -> DevLoginOut:
    """Выдаёт токен на сид-пользователя, минуя Telegram (§12.4).

    Пользователя эта ручка не создаёт — его заводит фикстура (§12.5).
    Токен — просто str(user.id), без подписи и без TTL: он существует только
    для локальной разработки, пока у бота нет домена под /setdomain.
    """
    if not settings.dev_auth:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "дев-вход выключен")
    if settings.seed_telegram_id is None:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "SEED_TELEGRAM_ID не задан — нечем логиниться",
        )
    user = await users.get_by_telegram_id(session, settings.seed_telegram_id)
    if user is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "сид-пользователь не найден — прогони python -m app.fixtures.seed",
        )
    return DevLoginOut(access_token=str(user.id), user=user_out(user))
