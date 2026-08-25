from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator

from fastapi import FastAPI
from sqlalchemy import text

from app.db import SessionLocal, engine
from app.logging_config import setup_logging


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    setup_logging()
    yield
    await engine.dispose()


app = FastAPI(title="Habit Tracker API", version="0.1.0", lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, str]:
    """Проверяет и процесс, и связь с БД — иначе смысла в ручке мало."""
    async with SessionLocal() as session:
        await session.execute(text("SELECT 1"))
    return {"status": "ok", "db": "ok"}
