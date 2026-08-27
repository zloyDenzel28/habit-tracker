"""Модели, общие для api, worker и bot.

Реэкспорт здесь обязателен: без него Alembic не увидит таблицы в Base.metadata
и сгенерирует пустую миграцию.
"""

from app.models.base import Base
from app.models.enums import (
    MAX_SNOOZE_COUNT,
    TERMINAL_STATUSES,
    OccurrenceStatus,
    SentMessageKind,
)
from app.models.habit import Habit
from app.models.habit_pause import HabitPause
from app.models.occurrence import Occurrence
from app.models.sent_message import SentMessage
from app.models.user import User

__all__ = [
    "MAX_SNOOZE_COUNT",
    "TERMINAL_STATUSES",
    "Base",
    "Habit",
    "HabitPause",
    "Occurrence",
    "OccurrenceStatus",
    "SentMessage",
    "SentMessageKind",
    "User",
]
