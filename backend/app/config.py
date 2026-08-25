"""Конфигурация всех трёх процессов. Только переменные окружения, без хардкодов."""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Без значения по умолчанию намеренно: хост БД зашивать в код нельзя,
    # пусть процесс падает громко, а не ходит молча не туда.
    database_url: str

    # Опционален: без токена api и worker работают, bot стартует заглушкой.
    telegram_bot_token: str | None = None

    # Локальный вход в обход Telegram Login Widget (§12.4 спеки).
    dev_auth: bool = True

    # На отладке ставится 5 секунд, чтобы прогнать жизненный цикл occurrence
    # за пару минут вместо часа.
    scheduler_tick_seconds: int = Field(default=60, ge=1)

    log_level: str = "INFO"


settings = Settings()
