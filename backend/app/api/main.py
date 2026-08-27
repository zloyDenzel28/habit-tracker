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


API_DESCRIPTION = """
REST для экранов раздела 9 спецификации. Второй клиент того же приложения —
бот в Telegram; оба зовут один сервисный слой, поэтому «выполнил» из веба и
«выполнил» из чата — буквально одно действие (инвариант 4).

### Как попробовать ручки прямо отсюда

1. `POST /auth/dev-login` — отдаёт токен сид-пользователя. Работает, только
   если `DEV_AUTH=true` и фикстуры прогнаны (`python -m app.fixtures.seed`).
2. Скопировать `access_token` из ответа.
3. Кнопка **Authorize** справа сверху, вставить токен.

Токен — это `str(user.id)`, без подписи и без срока жизни. Он существует
только для локальной разработки: настоящему Telegram Login нужен домен под
`/setdomain`, которого на localhost нет (§12.4).

### Время

Все `datetime` в запросах и ответах — UTC, с явным смещением (инвариант 2).
Единственное исключение — `schedule_time` у привычки: это локальное время
без таймзоны, «19:00» означает 19:00 у пользователя. Хранить его в UTC
нельзя, иначе переход на летнее время сдвинет расписание.

Поля с типом «дата» (`local_date`, границы heatmap, даты паузы) — это дни
по `User.timezone`, а не по часам того, кто читает API.

### Ошибки

Все — объектом `{"detail": "..."}`. Коды перечислены у каждой ручки;
доменные правила, стоящие за 400 и 409, описаны в `docs/requirements.md`.
"""

TAGS = [
    {"name": "auth", "description": "Вход. На localhost — в обход Telegram (§12.4)"},
    {"name": "users", "description": "Профиль и таймзона, экран «Настройки» (§9.5)"},
    {
        "name": "habits",
        "description": (
            "Привычка — это шаблон: расписание, длительность, паузы, архив. "
            "Статистика и heatmap тоже здесь, потому что считаются по привычке "
            "целиком. Экраны «Мои привычки» и «Привычка» (§9.2–9.4)"
        ),
    },
    {
        "name": "occurrences",
        "description": (
            "Занятие — конкретное выполнение в конкретный день, вся история и "
            "все статусы живут тут (инвариант 1). Четыре POST-ручки — те же "
            "четыре кнопки, что и в чате. Экран «Сегодня» (§9.1)"
        ),
    },
    {"name": "service", "description": "Служебное"},
]

app = FastAPI(
    title="Habit Tracker API",
    version="0.1.0",
    description=API_DESCRIPTION,
    openapi_tags=TAGS,
    lifespan=lifespan,
)

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


@app.get("/health", tags=["service"], summary="Живость процесса и связь с БД")
async def health() -> dict[str, str]:
    """Проверяет и процесс, и связь с БД — иначе смысла в ручке мало."""
    async with SessionLocal() as session:
        await session.execute(text("SELECT 1"))
    return {"status": "ok", "db": "ok"}
