"""Экран «Сегодня» (§9): список occurrences и кнопки действий.

Инвариант 4: одно и то же действие должно работать одинаково из веба и
из Telegram. Сравни с app/bot/handlers.py — тот же порядок (найти занятие
пользователя, вызвать переход, закоммитить), разница только в форме ответа:
здесь HTTP-код вместо реплики в чат. Сами доменные ошибки в HTTP превращает
общий обработчик в app/api/main.py, поэтому try/except здесь не нужен.
"""

from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, SessionDep
from app.api.responses import CONFLICT_TRANSITION, NOT_FOUND_OCCURRENCE, UNAUTHORIZED
from app.api.schemas import OccurrenceOut
from app.models import Occurrence, User
from app.services import occurrences
from app.services.habits import user_today

router = APIRouter(prefix="/occurrences", tags=["occurrences"], responses=UNAUTHORIZED)

# Четыре кнопки ведут себя в OpenAPI одинаково: чужое или несуществующее
# занятие — 404, запрещённый переход — 409.
ACTION_RESPONSES = {**NOT_FOUND_OCCURRENCE, **CONFLICT_TRANSITION}


@router.get("", response_model=list[OccurrenceOut], summary="Занятия на день")
async def list_occurrences(
    user: CurrentUser, session: SessionDep, day: date | None = None
) -> list[OccurrenceOut]:
    """§9: список на конкретный день, по умолчанию — сегодня по таймзоне
    пользователя (инвариант 2: дата не берётся из браузера)."""
    day = day or user_today(user)
    items = await occurrences.list_for_local_date(session, user.id, day)
    return [OccurrenceOut.from_occurrence(o) for o in items]


async def _get_owned(session: AsyncSession, user: User, occurrence_id: uuid.UUID) -> Occurrence:
    occurrence = await occurrences.get_for_user(session, occurrence_id, user.id)
    if occurrence is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "занятие не найдено")
    return occurrence


@router.post(
    "/{occurrence_id}/start",
    response_model=OccurrenceOut,
    summary="«Начал»",
    responses=ACTION_RESPONSES,
)
async def start(occurrence_id: uuid.UUID, user: CurrentUser, session: SessionDep) -> OccurrenceOut:
    """§5: notified/snoozed → in_progress.

    С этого момента отсчитывается длительность привычки: догоняющий пинг
    придёт через duration_minutes после нажатия, а не после планового времени.
    """
    occurrence = await _get_owned(session, user, occurrence_id)
    occurrences.start(occurrence)
    await session.commit()
    return OccurrenceOut.from_occurrence(occurrence)


@router.post(
    "/{occurrence_id}/snooze",
    response_model=OccurrenceOut,
    summary="«+5 мин»",
    responses=ACTION_RESPONSES,
)
async def snooze(occurrence_id: uuid.UUID, user: CurrentUser, session: SessionDep) -> OccurrenceOut:
    """§4: notified → snoozed, срок сдвигается на пять минут.

    Подряд можно отложить ограниченное число раз; на исчерпанном лимите
    ручка отвечает 409, а фронт к этому моменту уже прячет кнопку —
    признак приходит в поле can_snooze.
    """
    occurrence = await _get_owned(session, user, occurrence_id)
    occurrences.snooze(occurrence)
    await session.commit()
    return OccurrenceOut.from_occurrence(occurrence)


@router.post(
    "/{occurrence_id}/complete",
    response_model=OccurrenceOut,
    summary="«Выполнил»",
    responses=ACTION_RESPONSES,
)
async def complete(occurrence_id: uuid.UUID, user: CurrentUser, session: SessionDep) -> OccurrenceOut:
    """§5: → done. Единственный статус, который наращивает серию (§7).

    Разрешено не только из in_progress: подтвердить выполнение можно и сразу
    после уведомления, не нажимая «Начал».
    """
    occurrence = await _get_owned(session, user, occurrence_id)
    occurrences.complete(occurrence)
    await session.commit()
    return OccurrenceOut.from_occurrence(occurrence)


@router.post(
    "/{occurrence_id}/skip",
    response_model=OccurrenceOut,
    summary="«Пропустить сегодня» / «Не получилось»",
    responses=ACTION_RESPONSES,
)
async def skip(occurrence_id: uuid.UUID, user: CurrentUser, session: SessionDep) -> OccurrenceOut:
    """§5: → skipped. Осознанный отказ, серию обрывает (§7).

    Из in_progress тоже: тот, кто начал и не смог, нажимает «Не получилось» —
    ручка та же самая, отличается только подпись кнопки.
    """
    occurrence = await _get_owned(session, user, occurrence_id)
    occurrences.skip(occurrence)
    await session.commit()
    return OccurrenceOut.from_occurrence(occurrence)
