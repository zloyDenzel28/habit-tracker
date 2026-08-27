"""Учёт сообщений, отправленных в чат, и выборка тех, что пора погасить.

Находка 2: действие в вебе не отражалось в Telegram — сообщение оставалось
с живыми кнопками и выглядело как «ещё не отвечено». Чинится тем, что каждое
отправленное сообщение записывается сюда вместе со своим текстом, а джоб
закрытия (§6.4) потом гасит все незакрытые сообщения занятий, дошедших до
терминального статуса, — неважно, каким интерфейсом их туда довели.

Инвариант 4 соблюдён: решений о статусах занятия здесь нет ни одного. Модуль
отвечает на два вопроса — «что мы отправили» и «что пора погасить», а текст
итога собирает services/messages.py.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import contains_eager

from app.models import (
    TERMINAL_STATUSES,
    Occurrence,
    SentMessage,
    SentMessageKind,
)
from app.services.timeutils import ensure_aware, now_utc


def record(
    session: AsyncSession,
    occurrence: Occurrence,
    *,
    kind: SentMessageKind,
    message_id: int,
    text: str,
    at: datetime | None = None,
) -> SentMessage:
    """Запоминает отправленное сообщение вместе с его текстом.

    Текст — снимок, а не ссылка на способ его собрать: занятие изменится,
    а отправленное сообщение уже нет (см. докстринг модели SentMessage).
    """
    at = ensure_aware(at) if at else now_utc()
    sent = SentMessage(
        occurrence_id=occurrence.id,
        kind=kind,
        message_id=message_id,
        text=text,
        sent_at=at,
    )
    session.add(sent)
    return sent


def mark_closed(sent: SentMessage, *, at: datetime | None = None) -> SentMessage:
    """Кнопки убраны, итог дописан.

    Инвариант 7: повторно не перезаписываем — как и notified_at, отметка
    существует ровно для того, чтобы второй прогон ничего не делал.
    """
    at = ensure_aware(at) if at else now_utc()
    if sent.closed_at is None:
        sent.closed_at = at
    return sent


async def open_for_occurrence(
    session: AsyncSession, occurrence_id: uuid.UUID
) -> Sequence[SentMessage]:
    """Незакрытые сообщения одного занятия, старые первыми.

    Нужна диспетчеру: перед тем как отправить занятию новое уведомление
    (снуз вернул его в выборку), прошлые сообщения надо погасить — иначе
    в чате окажется два живых набора кнопок к одному и тому же занятию.
    """
    return (
        await session.scalars(
            select(SentMessage)
            .where(
                SentMessage.occurrence_id == occurrence_id,
                SentMessage.closed_at.is_(None),
            )
            .order_by(SentMessage.sent_at)
        )
    ).all()


async def find_open(
    session: AsyncSession, occurrence_id: uuid.UUID, message_id: int
) -> SentMessage | None:
    """Незакрытая запись по telegram-id сообщения.

    Для бота: он держит сообщение в руках и правит его сам, а сюда приходит
    только за снимком текста и чтобы поставить отметку.
    """
    return await session.scalar(
        select(SentMessage).where(
            SentMessage.occurrence_id == occurrence_id,
            SentMessage.message_id == message_id,
            SentMessage.closed_at.is_(None),
        )
    )


async def due_for_closing(
    session: AsyncSession, *, limit: int | None = None
) -> Sequence[SentMessage]:
    """§6.4: сообщения занятий, которые уже закрыты, а в чате ещё живые.

    Терминальный статус — единственное условие: как именно занятие туда
    попало (кнопка в чате, кнопка в вебе, ночной джоб), значения не имеет.
    paused сюда не входит и входить не должен — по §4 это отложенное будущее,
    из него занятие ещё вернётся в pending.

    FOR UPDATE ... SKIP LOCKED по той же причине, что и в выборках диспетчера:
    два экземпляра воркера не должны редактировать одно сообщение дважды.
    Блокируем только sent_messages (of=) — occurrence и user нужны на чтение.
    """
    stmt = (
        select(SentMessage)
        .join(SentMessage.occurrence)
        .where(
            SentMessage.closed_at.is_(None),
            Occurrence.status.in_(TERMINAL_STATUSES),
        )
        .order_by(SentMessage.sent_at)
        .options(
            contains_eager(SentMessage.occurrence).joinedload(
                Occurrence.user, innerjoin=True
            )
        )
        .with_for_update(skip_locked=True, of=SentMessage)
    )
    if limit is not None:
        stmt = stmt.limit(limit)
    return (await session.scalars(stmt)).all()
