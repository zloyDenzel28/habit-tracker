"""Стрики и статистика (§7).

Расчёт разделён на две части намеренно:
  * compute_streaks — чистая функция над списком «дата -> статус». Никакой БД,
    поэтому правила стрика проверяются юнит-тестами за миллисекунды;
  * habit_stats — тонкая обёртка, которая достаёт эти данные из Postgres.

§7 разрешает считать всё запросами к occurrences, отдельных таблиц не заводим.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Habit, Occurrence, OccurrenceStatus
from app.services.constants import STATS_WINDOW_DAYS
from app.services.pauses import is_paused_on, load_pause_windows
from app.services.timeutils import days_range, today_local

# Статусы, которые участвуют в проценте выполнения: done / (done+skipped+missed).
COUNTED_STATUSES = (
    OccurrenceStatus.done,
    OccurrenceStatus.skipped,
    OccurrenceStatus.missed,
)

# §7: skipped и missed ломают серию одинаково — решение заказчика.
BREAKING_STATUSES = frozenset({OccurrenceStatus.skipped, OccurrenceStatus.missed})


@dataclass(frozen=True, slots=True)
class Streaks:
    current: int
    best: int


@dataclass(frozen=True, slots=True)
class HabitStats:
    current_streak: int
    best_streak: int
    done: int
    skipped: int
    missed: int
    window_days: int

    @property
    def completion_rate(self) -> float | None:
        """Доля выполненных за окно. None, если считать пока не из чего —
        ноль здесь врал бы: «0%» и «данных нет» это разные вещи."""
        total = self.done + self.skipped + self.missed
        if total == 0:
            return None
        return self.done / total


def compute_streaks(
    days: Iterable[tuple[date, OccurrenceStatus]],
    *,
    reset_dates: Iterable[date] = (),
    today: date,
) -> Streaks:
    """Текущая серия и рекорд по правилам §7.

    Правила:
      * done — серия +1;
      * skipped и missed — серия обнуляется;
      * paused (и любой ещё не закрытый статус) — день не считается вовсе:
        не увеличивает серию и не ломает её;
      * даты из reset_dates обнуляют текущую серию, но не рекорд.

    В reset_dates попадает два вида событий: возобновление после паузы длиннее
    14 дней (§7) и восстановление привычки из архива (§8). Обнуления в будущем
    игнорируем: пауза обнуляет серию «при возобновлении», а не в момент, когда
    её только запланировали, — иначе форма заморозки не смогла бы показать
    пользователю, какую серию он сейчас потеряет.
    """
    resets = sorted(d for d in reset_dates if d <= today)
    ordered = sorted(days, key=lambda item: item[0])

    run = 0
    best = 0
    next_reset = 0

    for day, status in ordered:
        while next_reset < len(resets) and resets[next_reset] <= day:
            best = max(best, run)
            run = 0
            next_reset += 1

        if status is OccurrenceStatus.done:
            run += 1
            best = max(best, run)
        elif status in BREAKING_STATUSES:
            best = max(best, run)
            run = 0

    # Обнуление могло случиться уже после последней записи: например пауза
    # закончилась вчера, а первый день по расписанию будет только в понедельник.
    if next_reset < len(resets):
        best = max(best, run)
        run = 0

    return Streaks(current=run, best=max(best, run))


async def load_history(
    session: AsyncSession, habit_id: uuid.UUID
) -> list[tuple[date, OccurrenceStatus]]:
    """Вся история привычки в виде «дата -> статус», по возрастанию даты."""
    rows = await session.execute(
        select(Occurrence.local_date, Occurrence.status)
        .where(Occurrence.habit_id == habit_id)
        .order_by(Occurrence.local_date)
    )
    return [(row.local_date, row.status) for row in rows]


async def habit_stats(
    session: AsyncSession, habit: Habit, tz: ZoneInfo, *, today: date | None = None
) -> HabitStats:
    """Метрики MVP по одной привычке: серия, рекорд, процент за 30 дней."""
    today = today or today_local(tz)
    history = await load_history(session, habit.id)

    windows = await load_pause_windows(session, habit.id, tz)
    reset_dates = [w.resumes_on for w in windows if w.resets_streak]
    if habit.streak_reset_on is not None:
        reset_dates.append(habit.streak_reset_on)

    streaks = compute_streaks(history, reset_dates=reset_dates, today=today)

    window_start = today - timedelta(days=STATS_WINDOW_DAYS - 1)
    counts = dict.fromkeys(COUNTED_STATUSES, 0)
    for day, status in history:
        if window_start <= day <= today and status in counts:
            counts[status] += 1

    return HabitStats(
        current_streak=streaks.current,
        best_streak=streaks.best,
        done=counts[OccurrenceStatus.done],
        skipped=counts[OccurrenceStatus.skipped],
        missed=counts[OccurrenceStatus.missed],
        window_days=STATS_WINDOW_DAYS,
    )


async def heatmap(
    session: AsyncSession, habit: Habit, tz: ZoneInfo, *, start: date, end: date
) -> Sequence[tuple[date, OccurrenceStatus]]:
    """Календарь-«травка» (§7): по дню на каждую запись в диапазоне.

    Дни без occurrence и без паузы не возвращаются вовсе — по расписанию
    привычки в этот день ничего и не было.

    Дни паузы достраиваются из HabitPause, а не берутся из occurrences (§7).
    Генератор (§6.1) дни активной паузы пропускает и записей на них не
    создаёт, поэтому статус paused достаётся только занятиям, успевшим
    появиться до постановки паузы — на горизонте в двое суток. Для паузы
    в двадцать дней это два дня из двадцати, а остальные восемнадцать
    в календаре неотличимы от дней вне расписания.
    """
    rows = await session.execute(
        select(Occurrence.local_date, Occurrence.status)
        .where(
            Occurrence.habit_id == habit.id,
            Occurrence.local_date >= start,
            Occurrence.local_date <= end,
        )
        .order_by(Occurrence.local_date)
    )
    by_day: dict[date, OccurrenceStatus] = {row.local_date: row.status for row in rows}

    windows = await load_pause_windows(session, habit.id, tz)
    scheduled_days = set(habit.schedule_days)
    for day in days_range(start, end):
        # Occurrence — запись о том, что с днём реально случилось, и пауза её
        # не перекрывает: день, закрытый как done, остаётся done. Пауза только
        # заполняет дни, на которых записи нет.
        if day in by_day or not is_paused_on(windows, day):
            continue
        # Дни вне расписания привычки паузой не красим: без паузы их в
        # календаре тоже не было бы, и красить их — врать про расписание.
        if day.isoweekday() not in scheduled_days:
            continue
        by_day[day] = OccurrenceStatus.paused

    return sorted(by_day.items())
