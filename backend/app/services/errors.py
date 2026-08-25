"""Доменные исключения сервисного слоя.

Адаптеры (API-роутеры, хендлеры бота) ловят их и превращают в HTTP-код или
в текст ответа пользователю. Сервисы не знают ни про HTTP, ни про Telegram.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models.enums import OccurrenceStatus


class ServiceError(Exception):
    """База для всех ошибок бизнес-логики."""


class ValidationError(ServiceError):
    """Данные не прошли проверку до записи в БД."""


class UnknownTimezone(ValidationError):
    def __init__(self, name: str) -> None:
        self.name = name
        super().__init__(f"неизвестная таймзона: {name!r}")


class InvalidTransition(ServiceError):
    """Переход статуса, которого нет в §4 спеки."""

    def __init__(
        self,
        action: str,
        current: OccurrenceStatus,
        allowed: frozenset[OccurrenceStatus],
    ) -> None:
        self.action = action
        self.current = current
        self.allowed = allowed
        allowed_names = ", ".join(sorted(s.value for s in allowed))
        super().__init__(
            f"действие {action!r} недопустимо из статуса {current.value!r} "
            f"(допустимые: {allowed_names})"
        )


class AlreadyInStatus(InvalidTransition):
    """Occurrence уже находится в целевом статусе.

    Отдельный класс нужен из-за двойных нажатий: в Telegram кнопка под старым
    сообщением остаётся живой, и «Выполнил» легко нажать дважды. Адаптеру важно
    отличить это от настоящего нарушения жизненного цикла — второе нажатие
    не ошибка пользователя, а гонка интерфейса.
    """


class SnoozeLimitReached(ServiceError):
    """Снуз исчерпан: §4 разрешает максимум MAX_SNOOZE_COUNT переносов."""

    def __init__(self, limit: int) -> None:
        self.limit = limit
        super().__init__(f"снуз исчерпан: максимум {limit}")
