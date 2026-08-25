"""Паузы: приведение записей HabitPause к отрезкам дат.

Инвариант 8: HabitPause создаётся только явным действием пользователя.
Здесь пауз не создаём — только читаем и считаем их фактические границы.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import HabitPause
from app.services.constants import PAUSE_STREAK_RESET_DAYS
from app.services.timeutils import local_date_of


@dataclass(frozen=True, slots=True)
class PauseWindow:
    """Фактический отрезок паузы: обе даты включительно."""

    starts_on: date
    ends_on: date

    @property
    def days(self) -> int:
        return (self.ends_on - self.starts_on).days + 1

    @property
    def resets_streak(self) -> bool:
        """§7: пауза дольше 14 дней обнуляет текущую серию при возобновлении."""
        return self.days > PAUSE_STREAK_RESET_DAYS

    @property
    def resumes_on(self) -> date:
        """Первый день после паузы — момент, когда применяется обнуление."""
        return self.ends_on + timedelta(days=1)

    def contains(self, day: date) -> bool:
        return self.starts_on <= day <= self.ends_on


def effective_window(pause: HabitPause, tz: ZoneInfo) -> PauseWindow | None:
    """Границы паузы с учётом досрочного снятия.

    Если пользователь снял паузу, последним днём паузы считается день перед
    снятием: день, в который человек нажал «снять», привычка уже живая.
    Снятие в первый же день означает, что паузы фактически не было — вернём None,
    иначе она попадёт в расчёт стрика как реально пропущенный день.
    """
    ends_on = pause.ends_on
    if pause.cancelled_at is not None:
        cancelled_local = local_date_of(pause.cancelled_at, tz)
        ends_on = min(ends_on, cancelled_local - timedelta(days=1))
    if ends_on < pause.starts_on:
        return None
    return PauseWindow(starts_on=pause.starts_on, ends_on=ends_on)


async def load_pause_windows(
    session: AsyncSession, habit_id, tz: ZoneInfo
) -> list[PauseWindow]:
    """Все фактические паузы привычки, по возрастанию даты начала."""
    rows = await session.scalars(
        select(HabitPause)
        .where(HabitPause.habit_id == habit_id)
        .order_by(HabitPause.starts_on)
    )
    windows = [w for p in rows if (w := effective_window(p, tz)) is not None]
    return windows


def is_paused_on(windows: list[PauseWindow], day: date) -> bool:
    return any(w.contains(day) for w in windows)


async def active_pause(
    session: AsyncSession, habit_id, tz: ZoneInfo, day: date
) -> PauseWindow | None:
    """Пауза, накрывающая конкретный день, если такая есть."""
    for window in await load_pause_windows(session, habit_id, tz):
        if window.contains(day):
            return window
    return None
