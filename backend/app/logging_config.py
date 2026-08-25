import logging

from app.config import settings


def setup_logging() -> None:
    logging.basicConfig(
        level=settings.log_level.upper(),
        format="%(asctime)s %(levelname)-8s %(name)s | %(message)s",
        # Инвариант 2: в логах тоже UTC, иначе отладка планировщика превращается
        # в угадывание, какое время где показано.
        datefmt="%Y-%m-%dT%H:%M:%S%z",
    )
