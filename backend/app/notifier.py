"""Инвариант 5: отправка уведомлений только через этот интерфейс.

Прямых вызовов aiogram из сервисов и планировщика быть не должно. В MVP
единственная реализация — TelegramNotifier (шаг 4). Web Push, если появится,
станет второй реализацией без переписывания бизнес-логики.
"""

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
