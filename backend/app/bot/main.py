"""Процесс bot: aiogram Dispatcher в режиме polling (§2).

Принимает нажатия кнопок и пишет результат в БД. Отправку уведомлений делает
worker — Bot.send_message работает без polling, поэтому слушатель ему не нужен.
Поднимать здесь ещё и планировщик нельзя (инвариант 6 и §2).

Без токена процесс не падает: docker compose up обязан работать и на пустом
TELEGRAM_BOT_TOKEN.
"""

from __future__ import annotations

import asyncio
import logging

from aiogram import Dispatcher

from app.bot.handlers import router
from app.config import settings
from app.db import engine
from app.logging_config import setup_logging
from app.telegram import create_bot

log = logging.getLogger("bot")


async def main() -> None:
    setup_logging()
    if not settings.telegram_bot_token:
        log.warning("TELEGRAM_BOT_TOKEN пуст — кнопки работать не будут, процесс просто ждёт")
        await asyncio.Event().wait()
        return

    bot = create_bot(settings.telegram_bot_token)
    dispatcher = Dispatcher()
    dispatcher.include_router(router)

    me = await bot.get_me()
    log.info("polling запущен: @%s", me.username)
    try:
        # Слушаем только то, что реально обрабатываем: лишние типы апдейтов
        # Telegram копит и отдаёт пачкой после простоя контейнера.
        await dispatcher.start_polling(bot, allowed_updates=["message", "callback_query"])
    finally:
        # Иначе aiohttp ругается на незакрытую сессию при остановке контейнера.
        await bot.session.close()
        await engine.dispose()
        log.info("bot остановлен")


if __name__ == "__main__":
    asyncio.run(main())
