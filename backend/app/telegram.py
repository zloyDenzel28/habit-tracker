"""Единственное место, где проект разговаривает с Telegram на отправку.

Здесь живёт реализация Notifier поверх aiogram (инвариант 5). Отдельным
модулем, а не внутри notifier.py, чтобы сам протокол и LogNotifier остались
без зависимости от aiogram: тесты сервисного слоя тянут messages.py, а через
него notifier.py, и подтягивать за собой пол-фреймворка им незачем.

Bot создаётся и здесь, и в процессе bot: отправка (worker) и приём апдейтов
(bot) — разные процессы (§2), Bot.send_message работает без polling.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.notifier import Button

if TYPE_CHECKING:
    from app.models.user import User

log = logging.getLogger("telegram")


def create_bot(token: str) -> Bot:
    """Bot с parse_mode=HTML по умолчанию.

    Разметка задаётся один раз здесь, а не в каждом вызове: тексты в
    services/messages.py уже размечены HTML, и забыть parse_mode в одном
    месте означало бы показать человеку сырые теги.
    """
    return Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))


def keyboard(buttons: list[Button]) -> InlineKeyboardMarkup | None:
    """Кнопки домена -> инлайн-клавиатура.

    Все кнопки в один ряд, как в макете §5. Их максимум три, и подписи
    короткие — Telegram ужимает ряд по ширине экрана.
    """
    if not buttons:
        return None
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=b.text, callback_data=b.callback_data) for b in buttons]
        ]
    )


class TelegramNotifier:
    """Реальная отправка. Реализует протокол Notifier из app/notifier.py."""

    def __init__(self, bot: Bot) -> None:
        self._bot = bot

    async def send(self, user: "User", text: str, buttons: list[Button]) -> None:
        # telegram_id пользователя — он же chat_id личной переписки с ботом.
        # Написать первым Telegram не даст, пока человек не отправил /start:
        # это вернётся TelegramForbiddenError, и джоб отложит отправку до
        # следующего тика, не проставив notified_at.
        await self._bot.send_message(
            chat_id=user.telegram_id,
            text=text,
            reply_markup=keyboard(buttons),
        )
