"""Асинхронный движок и фабрика сессий. Общие для api, worker и bot."""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings

engine = create_async_engine(
    settings.database_url,
    echo=False,
    # Соединение может протухнуть, пока контейнер простаивал.
    pool_pre_ping=True,
)

SessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    # Иначе после commit() объекты становятся просроченными и любое обращение
    # к их полям вызывает ещё один поход в БД — а в async это ошибка.
    expire_on_commit=False,
)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Зависимость FastAPI: одна сессия на запрос."""
    async with SessionLocal() as session:
        yield session
