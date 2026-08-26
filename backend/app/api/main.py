import logging
from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.api.routers import auth, habits, occurrences, users
from app.db import SessionLocal, engine
from app.logging_config import setup_logging
from app.services.errors import (
    AlreadyInStatus,
    InvalidTransition,
    ServiceError,
    SnoozeLimitReached,
    ValidationError,
)

log = logging.getLogger("api")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    setup_logging()
    yield
    await engine.dispose()


app = FastAPI(title="Habit Tracker API", version="0.1.0", lifespan=lifespan)

app.include_router(auth.router)
app.include_router(users.router)
app.include_router(habits.router)
app.include_router(occurrences.router)


@app.exception_handler(ServiceError)
async def service_error_handler(request: Request, error: ServiceError) -> JSONResponse:
    """Единая точка превращения доменной ошибки в HTTP-код (инвариант 4):
    роутеры сами ничего не решают про бизнес-правила, это делает сервисный
    слой, а адаптер только выбирает код ответа — как explain() в хендлерах
    бота выбирает текст реплики.

    Порядок веток важен: AlreadyInStatus — подкласс InvalidTransition,
    match проверяет более узкий случай раньше общего.
    """
    match error:
        case AlreadyInStatus() | SnoozeLimitReached() | InvalidTransition():
            code = 409
        case ValidationError():
            code = 400
        case _:
            code = 400
    return JSONResponse(status_code=code, content={"detail": str(error)})


@app.exception_handler(IntegrityError)
async def integrity_error_handler(request: Request, error: IntegrityError) -> JSONResponse:
    """Уникальный индекс `(habit_id, scheduled_at)` — это бизнес-правило
    «одно занятие на привычку и время» (инвариант 7), а не сбой инфраструктуры.
    Проверить его заранее в сервисе нельзя: между SELECT и INSERT успевает
    вклиниться ночной джоб, поэтому последнее слово всё равно за БД.

    Мимо service_error_handler ошибка пролетала и превращалась в голый 500
    с трейсбеком в логах — см. находку 5. Подстраховка, а не замена починке
    причин: каждый долетевший сюда конфликт стоит разобрать отдельно, поэтому
    в лог он уходит целиком.
    """
    log.warning("конфликт уникальности на %s: %s", request.url.path, error.orig)
    return JSONResponse(
        status_code=409,
        content={"detail": "занятие на это время уже существует"},
    )


@app.get("/health")
async def health() -> dict[str, str]:
    """Проверяет и процесс, и связь с БД — иначе смысла в ручке мало."""
    async with SessionLocal() as session:
        await session.execute(text("SELECT 1"))
    return {"status": "ok", "db": "ok"}
