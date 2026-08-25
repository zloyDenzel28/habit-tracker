"""Сервисный слой: вся бизнес-логика проекта.

Инвариант 4: роутеры FastAPI, хендлеры бота и джобы планировщика — тонкие
адаптеры. Они разбирают ввод, зовут функцию отсюда и отдают ответ. Ни одного
решения о статусах, стриках или расписании за пределами этого пакета быть
не должно, иначе «выполнил» из веба и «выполнил» из Telegram однажды разойдутся.

Модули:
    timeutils   переходы UTC <-> локальное время пользователя
    constants   числа из спеки
    errors      доменные исключения
    occurrences жизненный цикл occurrence (§4) и выборки планировщика (§6.2)
    generation  создание occurrences по расписанию (§6.1)
    pauses      отрезки пауз (§3, §7)
    habits      создание, правка, архив, пауза, смена таймзоны (§8, §9)
    messages    тексты уведомлений и наборы кнопок (§5)
    stats       стрики и статистика (§7)
    users       поиск пользователя по telegram_id
"""

from app.services import (
    constants,
    errors,
    generation,
    habits,
    messages,
    occurrences,
    pauses,
    stats,
    timeutils,
    users,
)

__all__ = [
    "constants",
    "errors",
    "generation",
    "habits",
    "messages",
    "occurrences",
    "pauses",
    "stats",
    "timeutils",
    "users",
]
