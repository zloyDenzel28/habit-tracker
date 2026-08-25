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
from app.api.schemas import OccurrenceOut
from app.models import Occurrence, User
from app.services import occurrences
from app.services.habits import user_today

router = APIRouter(prefix="/occurrences", tags=["occurrences"])


@router.get("", response_model=list[OccurrenceOut])
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


@router.post("/{occurrence_id}/start", response_model=OccurrenceOut)
async def start(occurrence_id: uuid.UUID, user: CurrentUser, session: SessionDep) -> OccurrenceOut:
    occurrence = await _get_owned(session, user, occurrence_id)
    occurrences.start(occurrence)
    await session.commit()
    return OccurrenceOut.from_occurrence(occurrence)


@router.post("/{occurrence_id}/snooze", response_model=OccurrenceOut)
async def snooze(occurrence_id: uuid.UUID, user: CurrentUser, session: SessionDep) -> OccurrenceOut:
    occurrence = await _get_owned(session, user, occurrence_id)
    occurrences.snooze(occurrence)
    await session.commit()
    return OccurrenceOut.from_occurrence(occurrence)


@router.post("/{occurrence_id}/complete", response_model=OccurrenceOut)
async def complete(occurrence_id: uuid.UUID, user: CurrentUser, session: SessionDep) -> OccurrenceOut:
    occurrence = await _get_owned(session, user, occurrence_id)
    occurrences.complete(occurrence)
    await session.commit()
    return OccurrenceOut.from_occurrence(occurrence)


@router.post("/{occurrence_id}/skip", response_model=OccurrenceOut)
async def skip(occurrence_id: uuid.UUID, user: CurrentUser, session: SessionDep) -> OccurrenceOut:
    occurrence = await _get_owned(session, user, occurrence_id)
    occurrences.skip(occurrence)
    await session.commit()
    return OccurrenceOut.from_occurrence(occurrence)
