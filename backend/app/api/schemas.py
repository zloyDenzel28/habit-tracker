"""Pydantic-схемы под экраны раздела 9.

Никакой бизнес-логики: только форма запроса/ответа. Проверки вроде диапазона
дней недели или минимальной длительности остаются в services/habits.py
(инвариант 4) — здесь они бы задваивались и рано или поздно разошлись.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, time

from pydantic import BaseModel, ConfigDict

from app.config import settings
from app.models import Occurrence, OccurrenceStatus, User
from app.services import occurrences as occurrences_service
from app.services.constants import DEFAULT_DURATION_MINUTES

# --- пользователь / вход ----------------------------------------------------


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    telegram_id: int
    telegram_username: str | None
    first_name: str
    timezone: str
    created_at: datetime
    # Не поле пользователя, а конфиг приложения (TELEGRAM_BOT_USERNAME) — но
    # это единственная ручка, которую фронт грузит при каждом входе, и заводить
    # под одну строку отдельный эндпоинт незачем. Заполняется через user_out().
    bot_username: str | None = None


def user_out(user: User) -> UserOut:
    """Собрать UserOut и подмешать конфиг, которого нет на ORM-объекте.

    Три ручки отдают профиль (`/auth/dev-login`, `GET/PATCH /users/me`),
    и `bot_username` должен быть на месте у всех трёх — иначе, например,
    смена таймзоны молча стирала бы ссылку на бота из состояния фронта
    до следующей перезагрузки."""
    out = UserOut.model_validate(user)
    out.bot_username = settings.telegram_bot_username
    return out


class UserTimezoneUpdate(BaseModel):
    timezone: str


class TimezonePreviewOut(BaseModel):
    """Ответ на вопрос «Настроек» до сохранения: сколько сегодняшних занятий
    исчезнет при переезде в эту таймзону (§8)."""

    removed_today: int


class DevLoginOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


# --- привычка ----------------------------------------------------------------


class HabitCreate(BaseModel):
    title: str
    description: str | None = None
    duration_minutes: int = DEFAULT_DURATION_MINUTES
    schedule_days: list[int]
    schedule_time: time


class HabitUpdate(BaseModel):
    """Все поля опциональны — правится то, что пришло (§8, правка на месте).

    description отдельно от «не передано» отличается через exclude_unset на
    стороне роутера: null здесь — осознанное «стереть описание».
    """

    title: str | None = None
    description: str | None = None
    duration_minutes: int | None = None
    schedule_days: list[int] | None = None
    schedule_time: time | None = None


class HabitOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    description: str | None
    duration_minutes: int
    schedule_days: list[int]
    schedule_time: time
    is_archived: bool
    streak_reset_on: date | None
    created_at: datetime
    updated_at: datetime
    # Дата окончания активной сегодня паузы (находка 13) — считает бэк
    # (инвариант 4), список привычек не должен сам решать, идёт ли пауза.
    # Заполняется только в GET /habits; на остальных ручках остаётся None,
    # там пауза видна списком на экране привычки.
    paused_until: date | None = None


class HabitOverlapOut(BaseModel):
    """Короткая карточка привычки для предупреждения о пересечении (§9)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    schedule_time: time
    duration_minutes: int


class OverlapCheckRequest(BaseModel):
    schedule_days: list[int]
    schedule_time: time
    duration_minutes: int
    exclude_habit_id: uuid.UUID | None = None


# --- пауза ---------------------------------------------------------------


class HabitPauseCreate(BaseModel):
    starts_on: date
    ends_on: date | None = None


class HabitPauseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    starts_on: date
    ends_on: date
    cancelled_at: datetime | None


class PausePreviewOut(BaseModel):
    """Ответ на вопрос формы заморозки: обнулит ли эта пауза текущую серию (§7)."""

    resets_streak: bool


# --- статистика ------------------------------------------------------------


class HabitStatsOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    current_streak: int
    best_streak: int
    done: int
    skipped: int
    missed: int
    window_days: int
    completion_rate: float | None


class HeatmapDayOut(BaseModel):
    date: date
    status: OccurrenceStatus


# --- occurrence --------------------------------------------------------------


class OccurrenceOut(BaseModel):
    id: uuid.UUID
    habit_id: uuid.UUID
    habit_title: str
    local_date: date
    scheduled_at: datetime
    current_due_at: datetime
    duration_minutes: int
    status: OccurrenceStatus
    snooze_count: int
    notified_at: datetime | None
    followup_sent_at: datetime | None
    started_at: datetime | None
    finished_at: datetime | None
    can_start: bool
    can_snooze: bool
    can_complete: bool
    can_skip: bool

    @classmethod
    def from_occurrence(cls, occurrence: Occurrence) -> "OccurrenceOut":
        """Кнопки веб-экрана дублируют кнопки Telegram (§9), поэтому какие из
        них показывать решает не фронт, а те же наборы статусов, что уже
        публично объявлены в services/occurrences — как ACTIONS в хендлере
        бота, только для HTTP."""
        return cls(
            id=occurrence.id,
            habit_id=occurrence.habit_id,
            habit_title=occurrence.habit.title,
            local_date=occurrence.local_date,
            scheduled_at=occurrence.scheduled_at,
            current_due_at=occurrence.current_due_at,
            duration_minutes=occurrence.duration_minutes,
            status=occurrence.status,
            snooze_count=occurrence.snooze_count,
            notified_at=occurrence.notified_at,
            followup_sent_at=occurrence.followup_sent_at,
            started_at=occurrence.started_at,
            finished_at=occurrence.finished_at,
            can_start=occurrence.status in occurrences_service.START_FROM,
            can_snooze=occurrences_service.can_snooze(occurrence),
            can_complete=occurrence.status in occurrences_service.COMPLETE_FROM,
            can_skip=occurrence.status in occurrences_service.SKIP_FROM,
        )
