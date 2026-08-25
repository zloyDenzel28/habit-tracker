"""Процесс bot.

Шаг 1 — заглушка. Хендлеры кнопок и реальная отправка появятся на шаге 4.
Без токена процесс не падает: docker compose up обязан работать и на пустом
TELEGRAM_BOT_TOKEN.
"""

import asyncio
import logging

from app.config import settings
from app.logging_config import setup_logging

log = logging.getLogger("bot")


async def main() -> None:
    setup_logging()
    if settings.telegram_bot_token:
        log.info("токен найден, polling будет включён на шаге 4")
    else:
        log.warning("TELEGRAM_BOT_TOKEN пуст — бот работать не будет, это ожидаемо на шаге 1")
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
