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
from app.api.responses import (
    CONFLICT_SCHEDULE,
    NOT_FOUND_HABIT,
    NOT_FOUND_PAUSE,
    UNAUTHORIZED,
    VALIDATION,
)
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

router = APIRouter(prefix="/habits", tags=["habits"], responses=UNAUTHORIZED)

# Диапазон heatmap по умолчанию, если фронт не передал start/end. Это только
# ширина экрана, а не бизнес-правило — в отличие от STATS_WINDOW_DAYS (§7),
# который зашит в constants.py и участвует в расчёте процента выполнения.
DEFAULT_HEATMAP_DAYS = 90


@router.get("", response_model=list[HabitOut], summary="Список привычек")
async def list_habits(
    user: CurrentUser, session: SessionDep, include_archived: bool = False
) -> list[HabitOut]:
    """Экран «Мои привычки» (§9.2). Архивные по умолчанию скрыты.

    У каждой привычки заполняется paused_until, если на сегодня действует
    пауза, — карточке нужно показать «на паузе до …».
    """
    items = await habits.habits_of_user(session, user.id, include_archived=include_archived)
    tz = resolve_tz(user.timezone)
    paused_until = await habits.paused_until_today(session, (h.id for h in items), tz)
    result = []
    for h in items:
        out = HabitOut.model_validate(h)
        out.paused_until = paused_until.get(h.id)
        result.append(out)
    return result


@router.post(
    "",
    response_model=HabitOut,
    status_code=status.HTTP_201_CREATED,
    summary="Завести привычку",
    responses=VALIDATION,
)
async def create_habit(payload: HabitCreate, user: CurrentUser, session: SessionDep) -> HabitOut:
    """Создаёт шаблон и сразу генерирует занятия на ближайшие дни (§6.1).

    schedule_time — локальное время пользователя, без таймзоны (инвариант 3).
    """
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


@router.post(
    "/check-overlap",
    response_model=list[HabitOverlapOut],
    summary="Проверка пересечения окон",
)
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


@router.get(
    "/{habit_id}", response_model=HabitOut, summary="Привычка", responses=NOT_FOUND_HABIT
)
async def get_habit(habit: OwnedHabit) -> HabitOut:
    """Шапка экрана «Привычка» (§9.4). Статистика — отдельными ручками."""
    return HabitOut.model_validate(habit)


@router.patch(
    "/{habit_id}",
    response_model=HabitOut,
    summary="Изменить привычку",
    responses={**NOT_FOUND_HABIT, **VALIDATION, **CONFLICT_SCHEDULE},
)
async def update_habit(
    payload: HabitUpdate, habit: OwnedHabit, user: CurrentUser, session: SessionDep
) -> HabitOut:
    """Правка шаблона. Будущие занятия пересобираются под новое расписание,
    прошедшие остаются как были — история не переписывается.

    description допускает null («стереть»), поэтому в сервис он передаётся,
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


@router.post(
    "/{habit_id}/archive",
    response_model=HabitOut,
    summary="В архив",
    responses=NOT_FOUND_HABIT,
)
async def archive_habit(habit: OwnedHabit, session: SessionDep) -> HabitOut:
    """§8: будущие занятия удаляются, история сохраняется.

    Открытые занятия сегодняшнего дня закрываются как skipped — иначе
    диспетчер продолжит слать пинги по привычке, которой в списке уже нет.
    """
    await habits.archive_habit(session, habit)
    await session.commit()
    await session.refresh(habit)  # см. комментарий в update_habit про updated_at
    return HabitOut.model_validate(habit)


@router.post(
    "/{habit_id}/restore",
    response_model=HabitOut,
    summary="Вернуть из архива",
    responses=NOT_FOUND_HABIT,
)
async def restore_habit(habit: OwnedHabit, user: CurrentUser, session: SessionDep) -> HabitOut:
    """§8: занятия генерируются заново, серия считается с нуля.

    Обнуление не наказание, а следствие §7: пропущенные дни архива в серию
    не входят, и склеивать через них старую серию с новой было бы неправдой.
    """
    tz = resolve_tz(user.timezone)
    await habits.restore_habit(session, habit, tz)
    await session.commit()
    await session.refresh(habit)  # см. комментарий в update_habit про updated_at
    return HabitOut.model_validate(habit)


@router.get(
    "/{habit_id}/pauses",
    response_model=list[HabitPauseOut],
    summary="Действующие паузы",
    responses=NOT_FOUND_HABIT,
)
async def list_pauses(habit: OwnedHabit, user: CurrentUser, session: SessionDep) -> list[HabitPauseOut]:
    """Только те, что ещё не закончились и не сняты: экрану нужно показать,
    что снимать, а истёкшие паузы снимать нечего."""
    tz = resolve_tz(user.timezone)
    items = await habits.active_pauses(session, habit.id, tz)
    return [HabitPauseOut.model_validate(p) for p in items]


@router.post(
    "/{habit_id}/pauses",
    response_model=HabitPauseOut,
    status_code=status.HTTP_201_CREATED,
    summary="Поставить на паузу",
    responses={**NOT_FOUND_HABIT, **VALIDATION},
)
async def create_pause(
    payload: HabitPauseCreate, habit: OwnedHabit, session: SessionDep
) -> HabitPauseOut:
    """§3: без ends_on пауза ставится на неделю. Задним числом нельзя.

    Пауза бывает только по явной просьбе человека — системных пауз в этом
    приложении нет (инвариант 8).
    """
    pause = await habits.pause_habit(
        session, habit, starts_on=payload.starts_on, ends_on=payload.ends_on
    )
    await session.commit()
    return HabitPauseOut.model_validate(pause)


@router.get(
    "/{habit_id}/pause-preview",
    response_model=PausePreviewOut,
    summary="Обнулит ли эта пауза серию",
    responses=NOT_FOUND_HABIT,
)
async def preview_pause(habit: OwnedHabit, starts_on: date, ends_on: date) -> PausePreviewOut:
    """§7: предупреждение «пауза дольше 14 дней обнулит серию» до сохранения.

    habit используется только для проверки владения (инвариант 4 — те же
    правила доступа, что и у остальных ручек), сам расчёт от дат не зависит
    ни от какой другой записи."""
    return PausePreviewOut(resets_streak=habits.pause_resets_streak(starts_on, ends_on))


@router.post(
    "/{habit_id}/pauses/{pause_id}/cancel",
    response_model=HabitPauseOut,
    summary="Снять паузу досрочно",
    responses=NOT_FOUND_PAUSE,
)
async def cancel_pause(
    habit: OwnedHabit, pause_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> HabitPauseOut:
    """Оставшиеся дни паузы возвращаются в расписание, прошедшие — нет:
    они действительно были на паузе, и переписать их значило бы задним
    числом сделать их пропущенными."""
    pause = await session.get(HabitPause, pause_id)
    if pause is None or pause.habit_id != habit.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "пауза не найдена")
    tz = resolve_tz(user.timezone)
    await habits.cancel_pause(session, pause, habit, tz)
    await session.commit()
    return HabitPauseOut.model_validate(pause)


@router.get(
    "/{habit_id}/stats",
    response_model=HabitStatsOut,
    summary="Серии и процент выполнения",
    responses=NOT_FOUND_HABIT,
)
async def get_stats(habit: OwnedHabit, user: CurrentUser, session: SessionDep) -> HabitStatsOut:
    """§7: текущая серия, лучшая серия и процент за последние 30 дней.

    Серия — это подряд идущие запланированные дни, а не календарные:
    привычка на понедельник и четверг не рвётся из-за вторника. Дни паузы
    серию не ломают, но пауза длиннее двух недель обнуляет её при снятии.
    """
    tz = resolve_tz(user.timezone)
    result = await stats.habit_stats(session, habit, tz)
    return HabitStatsOut.model_validate(result)


@router.get(
    "/{habit_id}/heatmap",
    response_model=list[HeatmapDayOut],
    summary="Календарь выполнений",
    responses=NOT_FOUND_HABIT,
)
async def get_heatmap(
    habit: OwnedHabit,
    user: CurrentUser,
    session: SessionDep,
    start: date | None = None,
    end: date | None = None,
) -> list[HeatmapDayOut]:
    """По дню на каждую дату диапазона, где занятие было запланировано.
    Дни без занятия в ответ не попадают вовсе — это не то же самое, что
    пропущенный день. По умолчанию — 90 дней до сегодня."""
    end = end or habits.user_today(user)
    start = start or end - timedelta(days=DEFAULT_HEATMAP_DAYS - 1)
    rows = await stats.heatmap(session, habit, resolve_tz(user.timezone), start=start, end=end)
    return [HeatmapDayOut(date=d, status=s) for d, s in rows]
