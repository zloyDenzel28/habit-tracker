"""Процесс worker: расписание трёх джобов из §6 спеки.

Планировщик отдельным процессом, а не внутри API (§2): иначе при запуске API
в несколько реплик уведомления начнут дублироваться.

Все времена — UTC (инвариант 2). Таймзона планировщику передаётся строкой
намеренно: APScheduler 3.10 принимает только таймзоны pytz, а 3.11 перешёл
на zoneinfo. Строку "UTC" разбирают обе версии, объект — только своя.
"""

from __future__ import annotations

import asyncio
import logging
import signal

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.config import settings
from app.db import SessionLocal, engine
from app.logging_config import setup_logging
from app.notifier import LogNotifier, Notifier
from app.scheduler import jobs
from app.services.timeutils import now_utc

log = logging.getLogger("worker")

SCHEDULER_TZ = "UTC"

# §6.1: генератор occurrences запускается в 03:00 UTC.
GENERATOR_HOUR = 3


def build_scheduler(notifier: Notifier) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(
        timezone=SCHEDULER_TZ,
        job_defaults={
            # Если контейнер притормозил и запуск пропущен несколько раз,
            # выполняем один раз, а не столько, сколько накопилось.
            "coalesce": True,
            # Медленный тик не должен наезжать на следующий: иначе два
            # экземпляра диспетчера пойдут в БД одновременно.
            "max_instances": 1,
            # Запуск, опоздавший на минуту, всё ещё имеет смысл выполнить.
            "misfire_grace_time": 60,
        },
    )

    scheduler.add_job(
        jobs.generate_occurrences,
        CronTrigger(hour=GENERATOR_HOUR, minute=0, timezone=SCHEDULER_TZ),
        args=(SessionLocal,),
        id="generate_occurrences",
        name="§6.1 генератор occurrences",
        # Ночной джоб опаздывает безболезненно: горизонт генерации двое суток
        # как раз запас на такой случай.
        misfire_grace_time=3600,
    )

    scheduler.add_job(
        jobs.dispatch_notifications,
        IntervalTrigger(seconds=settings.scheduler_tick_seconds, timezone=SCHEDULER_TZ),
        args=(SessionLocal, notifier),
        id="dispatch_notifications",
        name="§6.2 диспетчер уведомлений",
        # Иначе первый проход случится только через тик, а на отладке хочется
        # видеть реакцию сразу после старта контейнера.
        next_run_time=now_utc(),
    )

    scheduler.add_job(
        jobs.close_days,
        CronTrigger(minute=0, timezone=SCHEDULER_TZ),
        args=(SessionLocal,),
        id="close_days",
        name="§6.3 закрытие дня",
    )

    return scheduler


def _install_signal_handlers(stop: asyncio.Event) -> None:
    """Ctrl+C и docker compose down должны гасить процесс без трейсбека."""
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:
            # Windows вне контейнера. Проект живёт в Docker, так что это
            # только страховка для запуска руками.
            pass


async def main() -> None:
    setup_logging()
    log.info("worker запущен, тик диспетчера = %s c", settings.scheduler_tick_seconds)

    # Разовый прогон генератора на старте. Планировщик держит расписание
    # в памяти, поэтому пропущенное во время простоя контейнера 03:00 сам
    # он не отработает. Джоб идемпотентен, лишний запуск ничего не портит.
    await jobs.generate_occurrences(SessionLocal)

    notifier = LogNotifier()
    scheduler = build_scheduler(notifier)
    scheduler.start()
    for job in scheduler.get_jobs():
        log.info("джоб %-24s следующий запуск %s", job.id, job.next_run_time)

    stop = asyncio.Event()
    _install_signal_handlers(stop)
    await stop.wait()

    log.info("worker останавливается")
    scheduler.shutdown(wait=True)
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
