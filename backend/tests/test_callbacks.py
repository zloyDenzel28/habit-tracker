"""Разбор callback_data и строка-итог под уведомлением (шаг 4).

Без БД и без aiogram: проверяем ровно то, что решает домен. Хендлер бота
сверх этого только ходит в БД и отвечает в Telegram.
"""

import uuid
from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo

from app.models import Habit, Occurrence, OccurrenceStatus
from app.services import messages

DUE = datetime(2026, 8, 25, 16, 0, tzinfo=timezone.utc)  # 19:00 в Москве
MSK = ZoneInfo("Europe/Moscow")


def make(status: OccurrenceStatus = OccurrenceStatus.notified) -> Occurrence:
    habit = Habit(
        title="Английский",
        duration_minutes=30,
        schedule_days=[1, 3, 5],
        schedule_time=time(19, 0),
    )
    occurrence = Occurrence(
        habit=habit,
        status=status,
        scheduled_at=DUE,
        current_due_at=DUE,
        duration_minutes=30,
        snooze_count=0,
    )
    occurrence.id = uuid.uuid4()
    return occurrence


def test_кнопка_разбирается_обратно_в_действие_и_id():
    occurrence = make()
    for action in messages.ACTIONS:
        assert messages.parse_callback_data(
            messages.callback_data(action, occurrence)
        ) == (action, occurrence.id)


def test_чужой_и_битый_callback_data_дают_none():
    """None, а не исключение: строка приходит снаружи и может быть любой."""
    occurrence_id = uuid.uuid4()
    assert messages.parse_callback_data("") is None
    assert messages.parse_callback_data("habit:done:1") is None
    assert messages.parse_callback_data(f"occ:explode:{occurrence_id}") is None
    assert messages.parse_callback_data("occ:done:не-uuid") is None
    assert messages.parse_callback_data(f"occ:done:{occurrence_id}:лишнее") is None


def test_итог_показывает_время_начала():
    occurrence = make(OccurrenceStatus.in_progress)
    occurrence.started_at = datetime(2026, 8, 25, 16, 3, tzinfo=timezone.utc)
    assert messages.action_note(occurrence, MSK) == "▶️ Начал в 19:03"


def test_итог_снуза_показывает_новое_время_а_не_плановое():
    occurrence = make(OccurrenceStatus.snoozed)
    occurrence.current_due_at = DUE.replace(minute=5)
    assert messages.action_note(occurrence, MSK) == "⏰ Перенесено на 19:05"


def test_итог_выполнения_и_пропуска_различаются():
    done = make(OccurrenceStatus.done)
    done.finished_at = DUE
    skipped = make(OccurrenceStatus.skipped)
    skipped.finished_at = DUE
    assert messages.action_note(done, MSK) == "✅ Выполнено в 19:00"
    assert messages.action_note(skipped, MSK) == "🚫 Пропущено в 19:00"


def test_итог_не_падает_без_отметки_времени():
    """complete из notified не пишет started_at — выдумывать его мы не будем."""
    occurrence = make(OccurrenceStatus.done)
    assert messages.action_note(occurrence, MSK) == "✅ Выполнено в —"
