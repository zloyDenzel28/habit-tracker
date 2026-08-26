"""Инфраструктура тестов, ходящих в настоящий Postgres.

Отдельная база `<POSTGRES_DB>_test` в том же контейнере `db` — не та, на
которой сидит живой сид-пользователь: тесты не должны сносить ручной сид.
Схема поднимается настоящими alembic-миграциями (не Base.metadata.create_all),
чтобы тестовая БД была тем же самым, что видит production-код, включая
constraint'ы и уникальные индексы из миграций.

Каждый тест получает сессию на своей SAVEPOINT внутри одной внешней
транзакции: что бы тест ни закоммитил через session.commit() (роутеры и
некоторые сервисы коммитят сами), после теста всё откатывается разом.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
from pathlib import Path

import asyncpg
import httpx
import pytest
import pytest_asyncio
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.api.main import app
from app.config import settings
from app.db import get_session
from app.models import User

BACKEND_DIR = Path(__file__).resolve().parent.parent

_BASE_URL: URL = make_url(settings.database_url)
TEST_DB_NAME = f"{_BASE_URL.database}_test"
TEST_URL: URL = _BASE_URL.set(database=TEST_DB_NAME)


async def _ensure_test_database() -> None:
    """Создаёт `<db>_test`, если её ещё нет. CREATE DATABASE не идёт внутри
    транзакции SQLAlchemy-движка, поэтому голый asyncpg-коннект к системной
    `postgres`."""
    conn = await asyncpg.connect(
        user=_BASE_URL.username,
        password=_BASE_URL.password,
        host=_BASE_URL.host,
        port=_BASE_URL.port,
        database="postgres",
    )
    try:
        exists = await conn.fetchval(
            "SELECT 1 FROM pg_database WHERE datname = $1", TEST_DB_NAME
        )
        if not exists:
            await conn.execute(f'CREATE DATABASE "{TEST_DB_NAME}"')
    finally:
        await conn.close()


def _run_migrations() -> None:
    """alembic upgrade head против тестовой БД, отдельным процессом:
    у alembic/env.py URL берётся из app.config.settings, а не из аргумента,
    поэтому проще переопределить его через переменную окружения, чем лезть
    в alembic API с уже импортированным модулем настроек."""
    env = os.environ.copy()
    env["DATABASE_URL"] = TEST_URL.render_as_string(hide_password=False)
    result = subprocess.run(
        ["alembic", "upgrade", "head"],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            "не удалось прогнать alembic upgrade head для тестовой БД:\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )


@pytest.fixture(scope="session", autouse=True)
def _test_database() -> None:
    asyncio.run(_ensure_test_database())
    _run_migrations()


@pytest_asyncio.fixture
async def db_session():
    """Сессия на тест, откат после — см. докстринг модуля."""
    engine = create_async_engine(TEST_URL, poolclass=NullPool)
    try:
        async with engine.connect() as conn:
            trans = await conn.begin()
            session = AsyncSession(
                bind=conn,
                expire_on_commit=False,
                join_transaction_mode="create_savepoint",
            )
            try:
                yield session
            finally:
                await session.close()
                await trans.rollback()
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def client(db_session: AsyncSession):
    """httpx-клиент поверх ASGI-приложения без поднятого uvicorn.

    get_session переопределён на db_session этого же теста: роутер и фабрики
    в тесте работают в одной транзакции, которую откатит db_session после.
    """

    async def _override_get_session():
        yield db_session

    app.dependency_overrides[get_session] = _override_get_session
    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac
    finally:
        app.dependency_overrides.pop(get_session, None)


def auth_headers(user: User) -> dict[str, str]:
    """Дев-токен (§12.4) — это просто str(user.id), без подписи и TTL."""
    return {"Authorization": f"Bearer {user.id}"}
