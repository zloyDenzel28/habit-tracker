"""Тексты уведомлений и наборы кнопок (§5).

Как и остальные тесты сервисного слоя, без БД: Occurrence и Habit собираются
руками. Проверяем ровно то, что решает домен, — какие кнопки видны и в какой
таймзоне показано время.
"""

import uuid
from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo

from app.models import MAX_SNOOZE_COUNT, Habit, Occurrence, OccurrenceStatus
from app.services import messages

# 19:00 в Москве, где живёт сид-пользователь.
DUE = datetime(2026, 8, 25, 16, 0, tzinfo=timezone.utc)
MSK = ZoneInfo("Europe/Moscow")


def make(
    status: OccurrenceStatus = OccurrenceStatus.notified,
    *,
    title: str = "Английский",
    snooze_count: int = 0,
) -> Occurrence:
    habit = Habit(
        title=title,
        duration_minutes=30,
        schedule_days=[1, 3, 5],
        schedule_time=time(19, 0),
    )
    return Occurrence(
        habit=habit,
        status=status,
        scheduled_at=DUE,
        current_due_at=DUE,
        duration_minutes=30,
        snooze_count=snooze_count,
    )


def labels(message: messages.Message) -> list[str]:
    return [button.text for button in message.buttons]


def test_первое_уведомление_показывает_локальное_время_и_длительность():
    message = messages.reminder(make(OccurrenceStatus.pending), MSK)
    assert "19:00" in message.text
    assert "30 мин" in message.text
    assert "Английский" in message.text


def test_первое_уведомление_даёт_четыре_кнопки():
    """Статус на момент сборки ещё pending: диспетчер сначала отправляет,
    потом помечает. Набор кнопок от этого не зависит."""
    message = messages.reminder(make(OccurrenceStatus.pending), MSK)
    assert labels(message) == [
        "▶️ Начал",
        "⏰ +5 мин",
        "✅ Выполнил",
        "🚫 Пропустить сегодня",
    ]


def test_на_исчерпанных_снузах_кнопка_плюс_пять_пропадает():
    """§4: при snooze_count = 5 пропадает только «+5 мин», остальные остаются."""
    message = messages.reminder(make(snooze_count=MAX_SNOOZE_COUNT), MSK)
    assert labels(message) == ["▶️ Начал", "✅ Выполнил", "🚫 Пропустить сегодня"]


def test_кнопка_снуза_есть_и_у_ещё_не_помеченной_записи():
    """Диспетчер сначала отправляет, потом ставит notified.

    То есть на момент сборки сообщения occurrence ещё pending — и если
    спрашивать occurrences.can_snooze, кнопка «+5 мин» не покажется никогда.
    """
    message = messages.reminder(make(OccurrenceStatus.pending), MSK)
    assert "⏰ +5 мин" in labels(message)


def test_первое_уведомление_включает_выполнил():
    """§5 (решение 26.08.2026): равняем по вебу — там «Выполнил» на notified
    уже есть (COMPLETE_FROM включает notified с шага 2)."""
    message = messages.reminder(make(OccurrenceStatus.notified), MSK)
    assert labels(message) == [
        "▶️ Начал",
        "⏰ +5 мин",
        "✅ Выполнил",
        "🚫 Пропустить сегодня",
    ]


def test_догоняющий_пинг_начавшему_предлагает_не_получилось():
    message = messages.followup(make(OccurrenceStatus.in_progress), MSK)
    assert labels(message) == ["✅ Выполнил", "❌ Не получилось"]


def test_догоняющий_пинг_не_отреагировавшему_предлагает_пропустить():
    message = messages.followup(make(OccurrenceStatus.notified), MSK)
    assert labels(message) == ["✅ Выполнил", "❌ Пропустить"]
    assert "19:00" in message.text


def test_название_привычки_экранируется():
    """Название вводит пользователь, а сообщение уходит с parse_mode=HTML."""
    message = messages.reminder(make(title="Чтение <b>вслух</b>"), MSK)
    assert "Чтение &lt;b&gt;вслух&lt;/b&gt;" in message.text


def test_callback_data_укладывается_в_лимит_телеграма():
    """Telegram обрезает callback_data длиннее 64 байт."""
    occurrence = make()
    occurrence.id = uuid.uuid4()
    for button in messages.reminder(occurrence, MSK).buttons:
        assert len(button.callback_data.encode()) <= 64
