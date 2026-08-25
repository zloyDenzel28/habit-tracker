"""Фикстуры для отладки (§12.5).

    docker compose exec api python -m app.fixtures.seed

Создаёт одного пользователя и четыре привычки: короткую, длинную, стоящую
на паузе и с историей на 60 дней назад. Без истории нечем проверять ни стрики,
ни heatmap, а ждать неделю ради одного графика бессмысленно.

История задана списками, а не случайными числами: ожидаемые серия и рекорд
известны заранее, поэтому фикстуры заодно работают проверкой расчёта.
Скрипт печатает посчитанные метрики — если они разошлись с ожидаемыми,
это видно сразу.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import SessionLocal, engine
from app.logging_config import setup_logging
from app.models import Habit, HabitPause, Occurrence, OccurrenceStatus, User
from app.services.habits import create_habit, pause_habit
from app.services.stats import habit_stats
from app.services.timeutils import combine_local, local_now, now_utc, resolve_tz

log = logging.getLogger("fixtures")

# Заглушка на случай пустого SEED_TELEGRAM_ID: всё, кроме доставки сообщений
# в Telegram, работает и с ней.
FALLBACK_TELEGRAM_ID = 100_000_000_001

# История «Зарядки», от самого старого дня к свежему. Число — сколько дней
# назад, статус — чем день закончился. Ожидаемый результат этого набора:
# текущая серия 11, рекорд 12 (см. разбор в конце файла).
HISTORY: list[tuple[int, OccurrenceStatus]] = (
    [(n, OccurrenceStatus.done) for n in range(60, 52, -1)]
    + [(52, OccurrenceStatus.missed)]
    + [(n, OccurrenceStatus.done) for n in range(51, 45, -1)]
    + [(45, OccurrenceStatus.skipped)]
    + [(n, OccurrenceStatus.done) for n in range(44, 40, -1)]
    # 40..25 — шестнадцатидневная пауза, она длиннее 14 дней и обнуляет серию
    + [(n, OccurrenceStatus.paused) for n in range(40, 24, -1)]
    + [(n, OccurrenceStatus.done) for n in range(24, 12, -1)]
    + [(12, OccurrenceStatus.missed)]
    + [(n, OccurrenceStatus.done) for n in range(11, 0, -1)]
)

LONG_PAUSE_FROM_DAYS_AGO = 40
LONG_PAUSE_TO_DAYS_AGO = 25

EXPECTED_CURRENT_STREAK = 11
EXPECTED_BEST_STREAK = 12


async def _reset_user(session: AsyncSession, telegram_id: int) -> None:
    """Полностью сносит прежнего сид-пользователя.

    Пересоздание, а не обновление: фикстуры должны давать один и тот же
    результат при любом числе запусков. Каскад по FK уносит привычки,
    occurrences и паузы.
    """
    existing = await session.scalar(select(User).where(User.telegram_id == telegram_id))
    if existing is None:
        return
    log.warning("сид-пользователь уже есть, пересоздаю: %s", existing.id)
    await session.execute(delete(User).where(User.id == existing.id))
    await session.flush()


def _history_rows(
    habit: Habit, tz: ZoneInfo, today: date
) -> list[dict]:
    """Готовые записи occurrences за прошедшие дни.

    Генератор (§6.1) такие создать не может — он намеренно не делает записей
    в прошлом. Поэтому историю пишем напрямую, зато с честными временными
    метками: без них экран привычки покажет пустые поля.
    """
    duration = timedelta(minutes=habit.duration_minutes)
    rows = []
    for days_ago, status in HISTORY:
        day = today - timedelta(days=days_ago)
        scheduled_at = combine_local(day, habit.schedule_time, tz)
        row = {
            "habit_id": habit.id,
            "user_id": habit.user_id,
            "local_date": day,
            "scheduled_at": scheduled_at,
            "current_due_at": scheduled_at,
            "duration_minutes": habit.duration_minutes,
            "status": status,
            "notified_at": None,
            "started_at": None,
            "finished_at": None,
            "followup_sent_at": None,
        }
        if status is OccurrenceStatus.done:
            row["notified_at"] = scheduled_at
            row["started_at"] = scheduled_at + timedelta(minutes=1)
            row["finished_at"] = scheduled_at + duration
            row["followup_sent_at"] = scheduled_at + duration
        elif status is OccurrenceStatus.skipped:
            row["notified_at"] = scheduled_at
            row["finished_at"] = scheduled_at + timedelta(minutes=2)
        elif status is OccurrenceStatus.missed:
            row["notified_at"] = scheduled_at
            row["followup_sent_at"] = scheduled_at + duration
            # Закрыто ночным джобом в полночь по таймзоне пользователя.
            row["finished_at"] = combine_local(day + timedelta(days=1), time(0, 0), tz)
        # paused: ни одной метки, день просто не считается
        rows.append(row)
    return rows


async def seed(session: AsyncSession) -> User:
    now = now_utc()
    tz = resolve_tz(settings.seed_timezone)
    today = local_now(tz).date()

    telegram_id = settings.seed_telegram_id or FALLBACK_TELEGRAM_ID
    if settings.seed_telegram_id is None:
        log.warning(
            "SEED_TELEGRAM_ID пуст, беру заглушку %s — уведомления в Telegram "
            "до этого пользователя не дойдут",
            FALLBACK_TELEGRAM_ID,
        )

    await _reset_user(session, telegram_id)

    user = User(
        telegram_id=telegram_id,
        telegram_username="seed_user",
        first_name="Тестовый",
        timezone=settings.seed_timezone,
    )
    session.add(user)
    await session.flush()

    # 1. Короткая привычка, время — через несколько минут после запуска фикстур.
    # Так шаг 3 можно проверить, не дожидаясь следующего утра.
    soon = (local_now(tz) + timedelta(minutes=3)).time().replace(second=0, microsecond=0)
    await create_habit(
        session,
        user,
        title="Отжимания",
        description="Короткая привычка: сработает через пару минут после сида",
        duration_minutes=5,
        schedule_days=[1, 2, 3, 4, 5, 6, 7],
        schedule_time=soon,
        now=now,
    )

    # 2. Длинная привычка по будним дням.
    await create_habit(
        session,
        user,
        title="Английский",
        description="Полчаса по понедельникам, средам и пятницам",
        duration_minutes=30,
        schedule_days=[1, 3, 5],
        schedule_time=time(19, 0),
        now=now,
    )

    # 3. Привычка на паузе. Сначала создаём, потом ставим паузу — именно так
    # это происходит у живого пользователя, и occurrences успевают получить
    # статус paused вместо того, чтобы просто не появиться.
    meditation = await create_habit(
        session,
        user,
        title="Медитация",
        description="Стоит на паузе на ближайшую неделю",
        duration_minutes=10,
        schedule_days=[1, 2, 3, 4, 5, 6, 7],
        schedule_time=time(7, 30),
        now=now,
    )
    await pause_habit(session, meditation, starts_on=today, ends_on=today + timedelta(days=7), now=now)

    # 4. Привычка с историей на 60 дней и длинной паузой внутри.
    workout = await create_habit(
        session,
        user,
        title="Зарядка",
        description="История на 60 дней: серии, пропуски и пауза длиннее 14 дней",
        duration_minutes=15,
        schedule_days=[1, 2, 3, 4, 5, 6, 7],
        schedule_time=time(8, 0),
        now=now,
    )
    session.add_all(
        Occurrence(**row) for row in _history_rows(workout, tz, today)
    )
    # Пауза заводится записью, а не только статусами occurrences: правило
    # «дольше 14 дней обнуляет серию» считается по HabitPause.
    session.add(
        HabitPause(
            habit_id=workout.id,
            starts_on=today - timedelta(days=LONG_PAUSE_FROM_DAYS_AGO),
            ends_on=today - timedelta(days=LONG_PAUSE_TO_DAYS_AGO),
        )
    )
    await session.flush()

    await _report(session, user, tz, today)
    return user


async def _report(session: AsyncSession, user: User, tz: ZoneInfo, today: date) -> None:
    """Печатает, что получилось. Заодно прогоняет расчёт стриков по-настоящему."""
    habits = (
        await session.scalars(select(Habit).where(Habit.user_id == user.id).order_by(Habit.title))
    ).all()

    log.info("пользователь %s (telegram_id=%s, tz=%s)", user.first_name, user.telegram_id, user.timezone)
    for habit in habits:
        stats = await habit_stats(session, habit, tz, today=today)
        rate = stats.completion_rate
        rate_text = "нет данных" if rate is None else f"{rate:.0%}"
        log.info(
            "  %-12s %s мин, дни %s, %s | серия %d, рекорд %d, за %d дней %s "
            "(done %d / skipped %d / missed %d)",
            habit.title,
            habit.duration_minutes,
            "".join(str(d) for d in habit.schedule_days),
            habit.schedule_time.strftime("%H:%M"),
            stats.current_streak,
            stats.best_streak,
            stats.window_days,
            rate_text,
            stats.done,
            stats.skipped,
            stats.missed,
        )
        if habit.title == "Зарядка":
            _check(stats.current_streak, EXPECTED_CURRENT_STREAK, "текущая серия")
            _check(stats.best_streak, EXPECTED_BEST_STREAK, "рекорд")


def _check(actual: int, expected: int, what: str) -> None:
    if actual != expected:
        log.error("  !! %s: ожидалось %d, посчитано %d", what, expected, actual)
    else:
        log.info("  ok %s = %d, как и ожидалось", what, expected)


async def main() -> None:
    setup_logging()
    async with SessionLocal() as session:
        await seed(session)
        await session.commit()
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
