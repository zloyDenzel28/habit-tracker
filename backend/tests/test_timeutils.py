"""Переходы между UTC и локальным временем (инварианты 2 и 3)."""

from datetime import date, datetime, time, timezone

import pytest

from app.services.errors import UnknownTimezone, ValidationError
from app.services.timeutils import (
    combine_local,
    days_range,
    ensure_aware,
    local_date_of,
    resolve_tz,
)

# Амстердам здесь не случайно и меняться на таймзону заказчика не должен.
# В Europe/Moscow перевода стрелок нет с 2014 года, поэтому на московских
# данных инвариант 3 (schedule_time хранится локальным временем без TZ)
# не проверяется вообще: тест был бы зелёным и на заведомо сломанном коде.
# Нужна зона, которая переходит на летнее время.
AMS = resolve_tz("Europe/Amsterdam")


def test_расписание_не_едет_при_переходе_на_летнее_время():
    """Ради этого schedule_time и хранится локальным временем без TZ.

    В Амстердаме зимой UTC+1, летом UTC+2. Привычка «в 19:00» обязана остаться
    в 19:00 по местному времени в обе даты, а UTC-момент при этом разный.
    """
    winter = combine_local(date(2026, 1, 15), time(19, 0), AMS)
    summer = combine_local(date(2026, 7, 15), time(19, 0), AMS)

    assert winter == datetime(2026, 1, 15, 18, 0, tzinfo=timezone.utc)
    assert summer == datetime(2026, 7, 15, 17, 0, tzinfo=timezone.utc)
    assert winter.astimezone(AMS).hour == summer.astimezone(AMS).hour == 19


def test_несуществующее_время_уезжает_вперёд_а_не_пропадает():
    """29 марта 2026 стрелки переводят с 02:00 на 03:00 — времени 02:30 в этот день нет.

    Важно, что привычка всё-таки сработает: один раз, часом позже.
    """
    moment = combine_local(date(2026, 3, 29), time(2, 30), AMS)
    assert moment.astimezone(AMS).hour == 3


def test_local_date_считается_по_таймзоне_пользователя():
    """Полночь в UTC — это ещё вчера в Америке и уже сегодня в Европе."""
    moment = datetime(2026, 8, 25, 0, 30, tzinfo=timezone.utc)
    assert local_date_of(moment, AMS) == date(2026, 8, 25)
    assert local_date_of(moment, resolve_tz("America/New_York")) == date(2026, 8, 24)


def test_naive_время_отвергается():
    with pytest.raises(ValidationError):
        ensure_aware(datetime(2026, 8, 25, 19, 0))


def test_неизвестная_таймзона_падает_громко():
    with pytest.raises(UnknownTimezone):
        resolve_tz("Europe/Atlantis")


def test_schedule_time_с_таймзоной_отвергается():
    with pytest.raises(ValidationError):
        combine_local(date(2026, 8, 25), time(19, 0, tzinfo=timezone.utc), AMS)


def test_days_range_включает_обе_границы():
    assert days_range(date(2026, 8, 25), date(2026, 8, 27)) == [
        date(2026, 8, 25),
        date(2026, 8, 26),
        date(2026, 8, 27),
    ]
    assert days_range(date(2026, 8, 27), date(2026, 8, 25)) == []
