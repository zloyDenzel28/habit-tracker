"""Инвариант 5: отправка уведомлений только через этот интерфейс.

Прямых вызовов aiogram из сервисов и планировщика быть не должно. Боевая
реализация — TelegramNotifier в app/telegram.py, здесь остаются протокол
и лог-версия. Web Push, если появится, станет третьей реализацией без
переписывания бизнес-логики.

Сам модуль намеренно не знает про aiogram: его тянут services/messages.py
и юнит-тесты, которым фреймворк не нужен.
"""

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from app.models.user import User


@dataclass(frozen=True, slots=True)
class Button:
    """Кнопка под уведомлением. callback_data разбирает хендлер бота."""

    text: str
    callback_data: str


class Notifier(Protocol):
    async def send(self, user: "User", text: str, buttons: list[Button]) -> None: ...


class LogNotifier:
    """Отправка, замоканная логом.

    Включается, когда TELEGRAM_BOT_TOKEN пуст. Планировщик при этом работает
    целиком: выборки, переходы статусов и защита от повторов — настоящие,
    наружу уходит только строчка в лог вместо сообщения. Удобно гонять джобы,
    не засоряя чат.
    """

    def __init__(self, logger: logging.Logger | None = None) -> None:
        self._log = logger or logging.getLogger("notifier")

    async def send(self, user: "User", text: str, buttons: list[Button]) -> None:
        self._log.info(
            "СООБЩЕНИЕ -> %s (tg %s): %s | кнопки: [%s]",
            user.first_name,
            user.telegram_id,
            # Текст может быть многострочным, а грепать логи удобнее по строке.
            text.replace("\n", " ⏎ "),
            "] [".join(f"{b.text} = {b.callback_data}" for b in buttons),
        )
