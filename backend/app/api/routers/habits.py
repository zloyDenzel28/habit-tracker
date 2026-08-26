"""Экраны «Мои привычки» и «Привычка» (§9).

Как и occurrences.py: разбор входа и вызов сервиса, без решений о бизнес-
правилах. Доменные ошибки превращает в HTTP-код общий обработчик в
app/api/main.py.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

from fastapi import APIRouter, HTTPException, status

from app.api.deps import CurrentUser, OwnedHabit, SessionDep
from app.api.schemas import (
    HabitCreate,
    HabitOut,
    HabitOverlapOut,
    HabitPauseCreate,
    HabitPauseOut,
    HabitStatsOut,
    HabitUpdate,
    HeatmapDayOut,
    OverlapCheckRequest,
    PausePreviewOut,
)
from app.models import HabitPause
from app.services import habits, stats
from app.services.timeutils import resolve_tz

router = APIRouter(prefix="/habits", tags=["habits"])

# Диапазон heatmap по умолчанию, если фронт не передал start/end. Это только
# ширина экрана, а не бизнес-правило — в отличие от STATS_WINDOW_DAYS (§7),
# который зашит в constants.py и участвует в расчёте процента выполнения.
DEFAULT_HEATMAP_DAYS = 90


@router.get("", response_model=list[HabitOut])
async def list_habits(
    user: CurrentUser, session: SessionDep, include_archived: bool = False
) -> list[HabitOut]:
    items = await habits.habits_of_user(session, user.id, include_archived=include_archived)
    return [HabitOut.model_validate(h) for h in items]


@router.post("", response_model=HabitOut, status_code=status.HTTP_201_CREATED)
async def create_habit(payload: HabitCreate, user: CurrentUser, session: SessionDep) -> HabitOut:
    habit = await habits.create_habit(
        session,
        user,
        title=payload.title,
        description=payload.description,
        duration_minutes=payload.duration_minutes,
        schedule_days=payload.schedule_days,
        schedule_time=payload.schedule_time,
    )
    await session.commit()
    return HabitOut.model_validate(habit)


@router.post("/check-overlap", response_model=list[HabitOverlapOut])
async def check_overlap(
    payload: OverlapCheckRequest, user: CurrentUser, session: SessionDep
) -> list[HabitOverlapOut]:
    """§9: предупреждение о пересечении окон при заполнении формы. Ничего
    не пишет — только читает, вызывается на каждое изменение полей формы."""
    overlaps = await habits.find_overlaps(
        session,
        user.id,
        schedule_days=payload.schedule_days,
        schedule_time=payload.schedule_time,
        duration_minutes=payload.duration_minutes,
        exclude_habit_id=payload.exclude_habit_id,
    )
    return [HabitOverlapOut.model_validate(h) for h in overlaps]


@router.get("/{habit_id}", response_model=HabitOut)
async def get_habit(habit: OwnedHabit) -> HabitOut:
    return HabitOut.model_validate(habit)


@router.patch("/{habit_id}", response_model=HabitOut)
async def update_habit(
    payload: HabitUpdate, habit: OwnedHabit, user: CurrentUser, session: SessionDep
) -> HabitOut:
    """description допускает null («стереть»), поэтому в сервис он передаётся,
    только если реально пришёл в теле запроса — иначе не отличить «стереть»
    от «не трогать» (services.habits.update_habit ждёт отдельный сентинел)."""
    fields = payload.model_dump(exclude_unset=True)
    kwargs = {
        key: fields[key]
        for key in ("title", "duration_minutes", "schedule_days", "schedule_time")
        if key in fields
    }
    if "description" in fields:
        kwargs["description"] = fields["description"]

    tz = resolve_tz(user.timezone)
    await habits.update_habit(session, habit, tz, **kwargs)
    await session.commit()
    # updated_at выставляется onupdate=func.now() на стороне Postgres, а не
    # в Python. После commit() SQLAlchemy не подтягивает его сама (сессия
    # с expire_on_commit=False), и попытка отдать это поле в ответе ловит
    # MissingGreenlet — синхронный доступ пытается сделать ленивый SELECT
    # вне await. refresh() — явный поход за актуальным значением.
    await session.refresh(habit)
    return HabitOut.model_validate(habit)


@router.post("/{habit_id}/archive", response_model=HabitOut)
async def archive_habit(habit: OwnedHabit, session: SessionDep) -> HabitOut:
    await habits.archive_habit(session, habit)
    await session.commit()
    await session.refresh(habit)  # см. комментарий в update_habit про updated_at
    return HabitOut.model_validate(habit)


@router.post("/{habit_id}/restore", response_model=HabitOut)
async def restore_habit(habit: OwnedHabit, user: CurrentUser, session: SessionDep) -> HabitOut:
    tz = resolve_tz(user.timezone)
    await habits.restore_habit(session, habit, tz)
    await session.commit()
    await session.refresh(habit)  # см. комментарий в update_habit про updated_at
    return HabitOut.model_validate(habit)


@router.get("/{habit_id}/pauses", response_model=list[HabitPauseOut])
async def list_pauses(habit: OwnedHabit, session: SessionDep) -> list[HabitPauseOut]:
    items = await habits.active_pauses(session, habit.id)
    return [HabitPauseOut.model_validate(p) for p in items]


@router.post("/{habit_id}/pauses", response_model=HabitPauseOut, status_code=status.HTTP_201_CREATED)
async def create_pause(
    payload: HabitPauseCreate, habit: OwnedHabit, session: SessionDep
) -> HabitPauseOut:
    pause = await habits.pause_habit(
        session, habit, starts_on=payload.starts_on, ends_on=payload.ends_on
    )
    await session.commit()
    return HabitPauseOut.model_validate(pause)


@router.get("/{habit_id}/pause-preview", response_model=PausePreviewOut)
async def preview_pause(habit: OwnedHabit, starts_on: date, ends_on: date) -> PausePreviewOut:
    """§7: предупреждение «пауза дольше 14 дней обнулит серию» до сохранения.

    habit используется только для проверки владения (инвариант 4 — те же
    правила доступа, что и у остальных ручек), сам расчёт от дат не зависит
    ни от какой другой записи."""
    return PausePreviewOut(resets_streak=habits.pause_resets_streak(starts_on, ends_on))


@router.post("/{habit_id}/pauses/{pause_id}/cancel", response_model=HabitPauseOut)
async def cancel_pause(
    habit: OwnedHabit, pause_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> HabitPauseOut:
    pause = await session.get(HabitPause, pause_id)
    if pause is None or pause.habit_id != habit.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "пауза не найдена")
    tz = resolve_tz(user.timezone)
    await habits.cancel_pause(session, pause, habit, tz)
    await session.commit()
    return HabitPauseOut.model_validate(pause)


@router.get("/{habit_id}/stats", response_model=HabitStatsOut)
async def get_stats(habit: OwnedHabit, user: CurrentUser, session: SessionDep) -> HabitStatsOut:
    tz = resolve_tz(user.timezone)
    result = await stats.habit_stats(session, habit, tz)
    return HabitStatsOut.model_validate(result)


@router.get("/{habit_id}/heatmap", response_model=list[HeatmapDayOut])
async def get_heatmap(
    habit: OwnedHabit,
    user: CurrentUser,
    session: SessionDep,
    start: date | None = None,
    end: date | None = None,
) -> list[HeatmapDayOut]:
    end = end or habits.user_today(user)
    start = start or end - timedelta(days=DEFAULT_HEATMAP_DAYS - 1)
    rows = await stats.heatmap(session, habit, resolve_tz(user.timezone), start=start, end=end)
    return [HeatmapDayOut(date=d, status=s) for d, s in rows]
