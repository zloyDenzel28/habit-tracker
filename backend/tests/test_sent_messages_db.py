"""services/sent_messages (§6.4, находка 2) против настоящего Postgres.

Выборки здесь фильтруют по статусу занятия и по отметке closed_at, то есть
живут в SQL, а не в объекте, — тестам без БД такое не проверить.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.models import OccurrenceStatus, SentMessage, SentMessageKind
from app.services import sent_messages
from tests.factories import make_habit, make_occurrence, make_user

AT = datetime(2026, 8, 26, 16, 0, tzinfo=timezone.utc)

NOTIFICATION_TEXT = "⏰ <b>Английский</b> — 19:00, 30 мин"
FOLLOWUP_TEXT = "⌛ <b>Английский</b> — 30 мин прошло. Выполнил?"


async def _occurrence(db_session, *, status: OccurrenceStatus, **overrides):
    user = await make_user(db_session)
    habit = await make_habit(db_session, user)
    return await make_occurrence(
        db_session,
        habit,
        scheduled_at=AT,
        current_due_at=AT,
        status=status,
        **overrides,
    )


async def _record(db_session, occurrence, *, kind, message_id, text, at=AT) -> SentMessage:
    sent = sent_messages.record(
        db_session, occurrence, kind=kind, message_id=message_id, text=text, at=at
    )
    await db_session.flush()
    return sent


async def test_запись_хранит_снимок_текста_и_id_сообщения(db_session):
    occurrence = await _occurrence(db_session, status=OccurrenceStatus.notified)

    sent = await _record(
        db_session,
        occurrence,
        kind=SentMessageKind.notification,
        message_id=4242,
        text=NOTIFICATION_TEXT,
    )
    await db_session.refresh(sent)

    assert sent.message_id == 4242
    assert sent.text == NOTIFICATION_TEXT
    assert sent.kind is SentMessageKind.notification
    assert sent.closed_at is None


async def test_гасить_пора_только_занятия_в_терминальном_статусе(db_session):
    """Как занятие туда попало — кнопкой в чате, кнопкой в вебе или ночным
    джобом — выборке безразлично. Это и есть починка находки 2."""
    open_occurrence = await _occurrence(db_session, status=OccurrenceStatus.in_progress)
    done = await _occurrence(db_session, status=OccurrenceStatus.done, finished_at=AT)
    await _record(
        db_session,
        open_occurrence,
        kind=SentMessageKind.notification,
        message_id=1,
        text=NOTIFICATION_TEXT,
    )
    await _record(
        db_session, done, kind=SentMessageKind.notification, message_id=2, text=NOTIFICATION_TEXT
    )

    due = await sent_messages.due_for_closing(db_session)

    assert [sent.message_id for sent in due] == [2]


async def test_гасятся_оба_сообщения_занятия(db_session):
    """Критерий шага 6: и первое уведомление, и догоняющий пинг."""
    occurrence = await _occurrence(db_session, status=OccurrenceStatus.done, finished_at=AT)
    await _record(
        db_session,
        occurrence,
        kind=SentMessageKind.notification,
        message_id=10,
        text=NOTIFICATION_TEXT,
    )
    await _record(
        db_session,
        occurrence,
        kind=SentMessageKind.followup,
        message_id=11,
        text=FOLLOWUP_TEXT,
        at=AT + timedelta(minutes=30),
    )

    due = await sent_messages.due_for_closing(db_session)

    # Порядок по времени отправки: сначала уведомление, потом пинг.
    assert [sent.message_id for sent in due] == [10, 11]


async def test_погашенное_сообщение_второй_раз_не_выбирается(db_session):
    """Инвариант 7: отметка closed_at делает повторный прогон пустым."""
    occurrence = await _occurrence(db_session, status=OccurrenceStatus.done, finished_at=AT)
    sent = await _record(
        db_session,
        occurrence,
        kind=SentMessageKind.notification,
        message_id=20,
        text=NOTIFICATION_TEXT,
    )

    sent_messages.mark_closed(sent, at=AT + timedelta(minutes=1))
    await db_session.flush()

    assert await sent_messages.due_for_closing(db_session) == []
    assert sent.closed_at == AT + timedelta(minutes=1)


async def test_повторная_отметка_не_перезаписывает_время(db_session):
    occurrence = await _occurrence(db_session, status=OccurrenceStatus.done, finished_at=AT)
    sent = await _record(
        db_session,
        occurrence,
        kind=SentMessageKind.notification,
        message_id=21,
        text=NOTIFICATION_TEXT,
    )

    sent_messages.mark_closed(sent, at=AT)
    sent_messages.mark_closed(sent, at=AT + timedelta(hours=1))

    assert sent.closed_at == AT


async def test_вытесненные_снузом_сообщения_видны_до_терминального_статуса(db_session):
    """Диспетчер гасит их сам перед отправкой нового уведомления: занятие
    ещё snoozed, то есть в выборку джоба §6.4 не попадает."""
    occurrence = await _occurrence(db_session, status=OccurrenceStatus.snoozed)
    await _record(
        db_session,
        occurrence,
        kind=SentMessageKind.notification,
        message_id=30,
        text=NOTIFICATION_TEXT,
    )

    assert await sent_messages.due_for_closing(db_session) == []
    stale = await sent_messages.open_for_occurrence(db_session, occurrence.id)
    assert [sent.message_id for sent in stale] == [30]


async def test_поиск_по_id_сообщения_не_видит_погашенных(db_session):
    """Бот ходит сюда за снимком текста: у уже погашенного его брать незачем."""
    occurrence = await _occurrence(db_session, status=OccurrenceStatus.notified)
    sent = await _record(
        db_session,
        occurrence,
        kind=SentMessageKind.notification,
        message_id=40,
        text=NOTIFICATION_TEXT,
    )

    found = await sent_messages.find_open(db_session, occurrence.id, 40)
    assert found is not None and found.text == NOTIFICATION_TEXT

    sent_messages.mark_closed(sent, at=AT)
    await db_session.flush()

    assert await sent_messages.find_open(db_session, occurrence.id, 40) is None
