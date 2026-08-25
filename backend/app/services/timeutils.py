"""Единственное место, где система переходит между UTC и локальным временем.

Инвариант 2: внутри всё в UTC. Локальное время появляется только через
User.timezone и только здесь. Ни один другой модуль не должен звать
datetime.now() или astimezone() напрямую.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.services.errors import UnknownTimezone, ValidationError

UTC = timezone.utc


def now_utc() -> datetime:
    """Текущий момент. Всегда aware — naive datetime в этом проекте вне закона."""
    return datetime.now(UTC)


def resolve_tz(name: str) -> ZoneInfo:
    """Имя IANA -> ZoneInfo. Падает громко, а не молча подставляет UTC."""
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise UnknownTimezone(name) from exc


def ensure_aware(moment: datetime) -> datetime:
    """Страховка от naive datetime, просочившегося из БД или из теста.

    Naive-момент не ошибка синтаксиса, но он молча считается локальным временем
    хоста и ломает весь расчёт. Лучше упасть на границе, чем разбираться потом,
    почему уведомление ушло на три часа раньше.
    """
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise ValidationError(f"ожидался aware datetime, получен naive: {moment!r}")
    return moment


def to_tz(moment: datetime, tz: ZoneInfo) -> datetime:
    """UTC-момент -> тот же момент в локальной таймзоне."""
    return ensure_aware(moment).astimezone(tz)


def local_date_of(moment: datetime, tz: ZoneInfo) -> date:
    """Какая календарная дата была у пользователя в этот момент."""
    return to_tz(moment, tz).date()


def local_now(tz: ZoneInfo) -> datetime:
    return to_tz(now_utc(), tz)


def today_local(tz: ZoneInfo) -> date:
    return local_date_of(now_utc(), tz)


def combine_local(day: date, at: time, tz: ZoneInfo) -> datetime:
    """Локальные дата и время -> UTC-момент.

    Именно ради этой функции Habit.schedule_time хранится без таймзоны
    (инвариант 3): смещение берётся на конкретную дату, поэтому «каждый день
    в 19:00» остаётся в 19:00 и после перехода на летнее время.

    Два пограничных случая перехода DST разрешаются поведением zoneinfo:
      * несуществующее время (стрелки перевели вперёд, 02:30 в этот день нет) —
        момент уезжает на час вперёд, привычка сработает в 03:30;
      * неоднозначное время (стрелки перевели назад, 02:30 бывает дважды) —
        берётся первое из двух, fold=0.
    Оба варианта дают один срабатывание в день, а не ноль и не два.
    """
    if at.tzinfo is not None:
        raise ValidationError("schedule_time должно быть без таймзоны (инвариант 3)")
    return datetime.combine(day, at, tzinfo=tz).astimezone(UTC)


def days_range(start: date, end: date) -> list[date]:
    """Все даты от start до end включительно."""
    if end < start:
        return []
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]
