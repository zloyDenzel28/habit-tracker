"""Процесс worker.

Шаг 1 — заглушка. Три джоба из §6 спеки появятся на шаге 3: генератор
occurrences, диспетчер уведомлений и закрытие дня.
"""

import asyncio
import logging

from app.config import settings
from app.logging_config import setup_logging

log = logging.getLogger("worker")


async def main() -> None:
    setup_logging()
    log.info("worker запущен, тик планировщика = %s c", settings.scheduler_tick_seconds)
    log.info("джобы будут добавлены на шаге 3")
    # Держим процесс живым, иначе контейнер уйдёт в перезапуск.
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
