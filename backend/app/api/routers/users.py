"""Экран «Настройки» (§9): профиль и смена таймзоны."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import CurrentUser, SessionDep
from app.api.schemas import UserOut, UserTimezoneUpdate
from app.services.habits import change_user_timezone

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me", response_model=UserOut)
async def get_me(user: CurrentUser) -> UserOut:
    return UserOut.model_validate(user)


@router.patch("/me", response_model=UserOut)
async def update_timezone(
    payload: UserTimezoneUpdate, user: CurrentUser, session: SessionDep
) -> UserOut:
    """§8: смена таймзоны пересобирает pending occurrences — это делает сервис,
    роутер только коммитит транзакцию."""
    await change_user_timezone(session, user, payload.timezone)
    await session.commit()
    return UserOut.model_validate(user)
