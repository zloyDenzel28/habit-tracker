"""Выборки по пользователю.

Пока одна: найти человека по его telegram_id. Нужна боту, чтобы связать
нажатие кнопки с записью в БД, и лежит в сервисах, а не в хендлере, потому
что тем же способом пользователя будет искать вход через Telegram (§12.4).
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User


async def get_by_telegram_id(session: AsyncSession, telegram_id: int) -> User | None:
    return await session.scalar(select(User).where(User.telegram_id == telegram_id))
