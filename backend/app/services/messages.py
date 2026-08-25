"""Тексты уведомлений и наборы кнопок (§5 спеки).

Какие кнопки показать — решение доменное: оно зависит от статуса occurrence
и числа снузов. Поэтому оно живёт здесь, а не в планировщике и не в хендлерах
бота (инвариант 4). Notifier получает готовый текст и готовый список кнопок
и ничего не решает.

Разметка — HTML, потому что TelegramNotifier (шаг 4) отправит сообщения с
parse_mode="HTML". Легаси-Markdown Telegram спотыкается на подчёркиваниях и
звёздочках в пользовательском тексте, а в HTML достаточно экранировать три
символа. Название привычки вводит пользователь, поэтому оно экранируется.
"""

from __future__ import annotations

import html
from dataclasses import dataclass
from zoneinfo import ZoneInfo

from app.models import MAX_SNOOZE_COUNT, Occurrence, OccurrenceStatus
from app.notifier import Button
from app.services.timeutils import to_tz

# Формат callback_data: "occ:<действие>:<uuid>". Разбирать его будет бот
# на шаге 4. Укладываемся в лимит Telegram в 64 байта: 4 + 7 + 36 = 47.
CALLBACK_PREFIX = "occ"

ACTION_START = "start"
ACTION_SNOOZE = "snooze"
ACTION_DONE = "done"
ACTION_SKIP = "skip"


@dataclass(frozen=True, slots=True)
class Message:
    """Готовое к отправке уведомление."""

    text: str
    buttons: list[Button]


def callback_data(action: str, occurrence: Occurrence) -> str:
    return f"{CALLBACK_PREFIX}:{action}:{occurrence.id}"


def _button(text: str, action: str, occurrence: Occurrence) -> Button:
    return Button(text=text, callback_data=callback_data(action, occurrence))


def _title(occurrence: Occurrence) -> str:
    return html.escape(occurrence.habit.title)


def _local_time(occurrence: Occurrence, tz: ZoneInfo) -> str:
    """Время срабатывания в таймзоне пользователя.

    Берём current_due_at, а не scheduled_at: после снуза человеку важно, на
    какое время перенесено выполнение, а не каким оно было по плану.
    """
    return to_tz(occurrence.current_due_at, tz).strftime("%H:%M")


def reminder(occurrence: Occurrence, tz: ZoneInfo) -> Message:
    """Первое уведомление в момент current_due_at (§5)."""
    buttons = [_button("▶️ Начал", ACTION_START, occurrence)]
    if occurrence.snooze_count < MAX_SNOOZE_COUNT:
        # §4: на шестой раз кнопка не показывается — остаются «Начал»
        # и «Пропустить».
        #
        # Спрашиваем только про счётчик, а не про occurrences.can_snooze:
        # тот проверяет ещё и статус notified, а сообщение собирается до
        # того, как диспетчер этот статус проставит (он сначала отправляет,
        # потом помечает). Вопрос здесь другой — «остались ли снузы»,
        # потому что reminder() вызывается ровно для уходящего уведомления.
        buttons.append(_button("⏰ +5 мин", ACTION_SNOOZE, occurrence))
    buttons.append(_button("🚫 Пропустить сегодня", ACTION_SKIP, occurrence))
    return Message(
        text=(
            f"⏰ <b>{_title(occurrence)}</b> — "
            f"{_local_time(occurrence, tz)}, {occurrence.duration_minutes} мин"
        ),
        buttons=buttons,
    )


def followup(occurrence: Occurrence, tz: ZoneInfo) -> Message:
    """Догоняющий пинг «Выполнил?» (§5).

    Два случая различаются только формулировкой: тот, кто нажал «Начал»,
    отвечает «Не получилось», а тот, кто не отреагировал вовсе, — «Пропустить».
    Действие за обеими кнопками одно и то же (skipped): человек ответил
    осознанно, а missed по §11 означает «не отреагировал».
    """
    title = _title(occurrence)
    if occurrence.status is OccurrenceStatus.in_progress:
        text = f"⌛ <b>{title}</b> — {occurrence.duration_minutes} мин прошло. Выполнил?"
        negative = "❌ Не получилось"
    else:
        text = f"⌛ <b>{title}</b> — было в {_local_time(occurrence, tz)}. Успел выполнить?"
        negative = "❌ Пропустить"
    return Message(
        text=text,
        buttons=[
            _button("✅ Выполнил", ACTION_DONE, occurrence),
            _button(negative, ACTION_SKIP, occurrence),
        ],
    )
