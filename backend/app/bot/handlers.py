"""Хендлеры бота: разобрал ввод, позвал сервис, ответил человеку.

Инвариант 4: решений о статусах здесь нет ни одного, все переходы — вызовы
services/occurrences. То же действие из веба (шаг 5) пойдёт через те же
функции и сработает одинаково.

Тексты уведомлений живут в services/messages.py, а короткие ответы на нажатие
— здесь: это реплики адаптера про судьбу самой кнопки, а не содержание
напоминания. Аналог текста HTTP-ошибки в роутере.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import CommandStart
from aiogram.types import CallbackQuery, Message

from app.db import SessionLocal
from app.models import Occurrence
from app.services import messages, occurrences, users
from app.services.errors import (
    AlreadyInStatus,
    InvalidTransition,
    ServiceError,
    SnoozeLimitReached,
)
from app.services.timeutils import resolve_tz

log = logging.getLogger("bot.handlers")

router = Router(name="occurrences")

# Кнопка -> переход. Больше про кнопки хендлеру знать нечего.
ACTIONS: dict[str, Callable[[Occurrence], Occurrence]] = {
    messages.ACTION_START: occurrences.start,
    messages.ACTION_SNOOZE: occurrences.snooze,
    messages.ACTION_DONE: occurrences.complete,
    messages.ACTION_SKIP: occurrences.skip,
}

# Всплывающая подсказка после удачного нажатия.
TOASTS: dict[str, str] = {
    messages.ACTION_START: "Засёк время",
    messages.ACTION_SNOOZE: "Напомню через 5 минут",
    messages.ACTION_DONE: "Отлично!",
    messages.ACTION_SKIP: "Ладно, бывает",
}

UNKNOWN_BUTTON = "Не знаю такой кнопки — похоже, она из старой версии бота."
UNKNOWN_USER = (
    "Не нахожу тебя в базе. Проверь SEED_TELEGRAM_ID в .env "
    "и запусти фикстуры заново."
)
NOT_FOUND = "Не нахожу это занятие. Возможно, привычку удалили."
FAILED = "Что-то пошло не так, попробуй ещё раз."


def explain(error: ServiceError) -> str:
    """Доменная ошибка -> реплика человеку.

    Ни одна из них не баг: кнопка под старым сообщением в Telegram остаётся
    кликабельной сколько угодно долго, поэтому повторное нажатие и нажатие
    на уже закрытом занятии — штатный сценарий, а не сбой.
    """
    match error:
        case AlreadyInStatus():
            return "Это уже отмечено."
        case SnoozeLimitReached():
            return "Переносить больше нельзя — пять раз уже было."
        case InvalidTransition():
            return "Занятие уже закрыто, кнопка не действует."
        case _:
            return FAILED


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    """/start. Нужен в первую очередь Telegram: без него бот не вправе писать.

    Пользователей здесь не заводим — по §12.5 их создаёт сид, и телеграмный
    id у пользователя уникален. Поэтому просто показываем id, чтобы его было
    откуда взять для .env.
    """
    if message.from_user is None:
        return
    telegram_id = message.from_user.id
    async with SessionLocal() as session:
        user = await users.get_by_telegram_id(session, telegram_id)

    if user is None:
        log.info("/start от незнакомого telegram_id %s", telegram_id)
        await message.answer(
            f"Привет! Твой telegram_id: <code>{telegram_id}</code>\n\n"
            "Положи его в <code>SEED_TELEGRAM_ID</code> в <code>.env</code>, "
            "перезапусти контейнеры и прогони фикстуры — "
            "и напоминания начнут приходить сюда."
        )
        return

    log.info("/start от %s (%s)", user.first_name, telegram_id)
    await message.answer(
        f"Привет, {user.first_name}! Напоминания буду присылать сюда. "
        "Отвечать на них — кнопками под сообщением."
    )


@router.callback_query(F.data.startswith(f"{messages.CALLBACK_PREFIX}:"))
async def on_occurrence_action(callback: CallbackQuery) -> None:
    """Нажатие кнопки под уведомлением."""
    parsed = messages.parse_callback_data(callback.data or "")
    if parsed is None:
        await callback.answer(UNKNOWN_BUTTON, show_alert=True)
        return
    action, occurrence_id = parsed

    note = await _apply(callback, action, occurrence_id)
    if note is None:
        # Человеку уже ответили внутри — там понятнее, что именно пошло не так.
        return

    await callback.answer(TOASTS[action])
    await _close_message(callback, note)


async def _apply(callback: CallbackQuery, action: str, occurrence_id: uuid.UUID) -> str | None:
    """Одно нажатие — одна транзакция. Возвращает строку-итог либо None.

    None означает «ответ человеку уже отправлен»: дальше сообщение не трогаем,
    кнопки остаются на месте, чтобы можно было нажать ещё раз.
    """
    async with SessionLocal() as session, session.begin():
        user = await users.get_by_telegram_id(session, callback.from_user.id)
        if user is None:
            await callback.answer(UNKNOWN_USER, show_alert=True)
            return None

        # Только get_for_user: он проверяет владельца, иначе подделанный
        # callback_data дал бы доступ к чужому занятию.
        occurrence = await occurrences.get_for_user(session, occurrence_id, user.id)
        if occurrence is None:
            log.warning("telegram_id %s дёрнул чужой или несуществующий occurrence %s",
                        user.telegram_id, occurrence_id)
            await callback.answer(NOT_FOUND, show_alert=True)
            return None

        try:
            ACTIONS[action](occurrence)
        except ServiceError as error:
            # До изменения объекта, так что откатывать нечего.
            log.info("нажатие %s по occurrence %s отклонено: %s", action, occurrence_id, error)
            await callback.answer(explain(error), show_alert=True)
            return None

        # Симметрично диспетчеру, который пишет в лог каждую отправку:
        # иначе удачное нажатие не оставляет следа и отлаживать цикл
        # по логам не выходит.
        log.info(
            "%s: %s -> %s (occurrence %s)",
            occurrence.habit.title,
            action,
            occurrence.status.value,
            occurrence.id,
        )

        # Собираем итог, пока сессия открыта: после commit объект живой
        # (expire_on_commit=False), но привычка и таймзона нужны здесь.
        return messages.action_note(occurrence, resolve_tz(user.timezone))


async def _close_message(callback: CallbackQuery, note: str) -> None:
    """Дописывает итог в уведомление и убирает кнопки.

    Кнопки убираем сразу, а не полагаемся на доменную ошибку при повторном
    нажатии: сообщение в чате должно показывать текущее положение дел, иначе
    через день не понять, отвечал ты на него или нет.
    """
    message = callback.message
    if not isinstance(message, Message) or message.text is None:
        # Сообщение старше 48 часов Telegram отдаёт как InaccessibleMessage:
        # редактировать его нельзя, но действие уже записано в БД.
        return
    try:
        # html_text возвращает исходный текст с разметкой — иначе <b> из
        # уведомления при редактировании превратится в сырые теги.
        await message.edit_text(f"{message.html_text}\n\n{note}")
    except TelegramBadRequest as error:
        log.warning("не удалось отредактировать сообщение %s: %s", message.message_id, error)


@router.callback_query()
async def on_unknown_callback(callback: CallbackQuery) -> None:
    """Всё остальное. Без ответа Telegram крутит часики на кнопке минуту."""
    log.warning("незнакомый callback_data: %r", callback.data)
    await callback.answer(UNKNOWN_BUTTON, show_alert=True)
