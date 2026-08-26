"""Экран «Настройки» (§9): профиль и смена таймзоны."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import CurrentUser, SessionDep
from app.api.schemas import TimezonePreviewOut, UserOut, UserTimezoneUpdate, user_out
from app.services.habits import change_user_timezone, preview_timezone_change

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me", response_model=UserOut)
async def get_me(user: CurrentUser) -> UserOut:
    return user_out(user)


@router.get("/timezone-preview", response_model=TimezonePreviewOut)
async def preview_timezone(
    timezone: str, user: CurrentUser, session: SessionDep
) -> TimezonePreviewOut:
    """§8: сколько сегодняшних занятий исчезнет, если сохранить эту таймзону.

    Ничего не пишет и профиль не трогает — «Настройки» дёргают её на каждый
    выбор в списке, до нажатия «Сохранить». Неизвестная таймзона даёт 400
    тем же путём, что и PATCH: проверку делает resolve_tz в сервисе.
    """
    removed = await preview_timezone_change(session, user, timezone)
    return TimezonePreviewOut(removed_today=removed)


@router.patch("/me", response_model=UserOut)
async def update_timezone(
    payload: UserTimezoneUpdate, user: CurrentUser, session: SessionDep
) -> UserOut:
    """§8: смена таймзоны пересобирает pending occurrences — это делает сервис,
    роутер только коммитит транзакцию."""
    await change_user_timezone(session, user, payload.timezone)
    await session.commit()
    return user_out(user)
