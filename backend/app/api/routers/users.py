"""Экран «Настройки» (§9): профиль и смена таймзоны."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import CurrentUser, SessionDep
from app.api.responses import CONFLICT_SCHEDULE, UNAUTHORIZED, VALIDATION
from app.api.schemas import TimezonePreviewOut, UserOut, UserTimezoneUpdate, user_out
from app.services.habits import change_user_timezone, preview_timezone_change

router = APIRouter(prefix="/users", tags=["users"], responses=UNAUTHORIZED)


@router.get("/me", response_model=UserOut, summary="Профиль")
async def get_me(user: CurrentUser) -> UserOut:
    """Профиль владельца токена.

    Отдаёт заодно bot_username из конфига — фронт грузит эту ручку при каждом
    входе, и заводить под одну строку отдельный эндпоинт незачем.
    """
    return user_out(user)


@router.get(
    "/timezone-preview",
    response_model=TimezonePreviewOut,
    summary="Что будет, если переехать в эту таймзону",
    responses=VALIDATION,
)
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


@router.patch(
    "/me",
    response_model=UserOut,
    summary="Переезд в другую таймзону",
    responses={**VALIDATION, **CONFLICT_SCHEDULE},
)
async def update_timezone(
    payload: UserTimezoneUpdate, user: CurrentUser, session: SessionDep
) -> UserOut:
    """§8: смена таймзоны пересобирает pending occurrences — это делает сервис,
    роутер только коммитит транзакцию.

    Операция с последствиями, а не настройка отображения: занятия, чьё новое
    время уже прошло, удаляются — иначе диспетчер пришлёт уведомление в ту же
    секунду. Сколько их будет, показывает GET /users/timezone-preview.
    Запущенные занятия (notified, snoozed, in_progress) не трогаются.
    """
    await change_user_timezone(session, user, payload.timezone)
    await session.commit()
    return user_out(user)
