"""Зависимости FastAPI: сессия на запрос, текущий пользователь, владение привычкой."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.models import Habit, User

# auto_error=False: без токена хотим отдать свою реплику, а не стандартную
# от HTTPBearer.
bearer_scheme = HTTPBearer(auto_error=False)

SessionDep = Annotated[AsyncSession, Depends(get_session)]


async def get_current_user(
    session: SessionDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> User:
    """Дев-токен (§12.4) — это id пользователя, без подписи и без TTL.

    Настоящего Telegram Login здесь нет: ему нужен домен для /setdomain,
    которого при локальной разработке не будет. Токен выдаёт только
    POST /auth/dev-login и только на сид-пользователя — расширять эту схему
    до продакшен-авторизации не нужно, она для этого не предназначена.
    """
    if credentials is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "нужен токен авторизации")
    try:
        user_id = uuid.UUID(credentials.credentials)
    except ValueError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "битый токен") from exc

    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "пользователь не найден")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


async def get_owned_habit(habit_id: uuid.UUID, session: SessionDep, user: CurrentUser) -> Habit:
    """Привычка по id, но только если она принадлежит текущему пользователю.

    404, а не 403 — чтобы не подтверждать чужому пользователю сам факт
    существования id.
    """
    habit = await session.get(Habit, habit_id)
    if habit is None or habit.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "привычка не найдена")
    return habit


OwnedHabit = Annotated[Habit, Depends(get_owned_habit)]
