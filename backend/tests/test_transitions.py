"""Жизненный цикл occurrence (§4, §5).

Переходы не ходят в БД, поэтому объект Occurrence создаётся руками —
поднимать Postgres ради проверки правил не нужно.
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.models import MAX_SNOOZE_COUNT, Occurrence, OccurrenceStatus
from app.services import occurrences as occ
from app.services.errors import (
    AlreadyInStatus,
    InvalidTransition,
    SnoozeLimitReached,
    ValidationError,
)

DUE = datetime(2026, 8, 25, 19, 0, tzinfo=timezone.utc)


def make(status: OccurrenceStatus = OccurrenceStatus.pending, **kwargs) -> Occurrence:
    defaults = {
        "status": status,
        "current_due_at": DUE,
        "scheduled_at": DUE,
        "duration_minutes": 30,
        "snooze_count": 0,
        "notified_at": None,
        "followup_sent_at": None,
        "started_at": None,
        "finished_at": None,
    }
    defaults.update(kwargs)
    return Occurrence(**defaults)


def test_pending_переходит_в_notified():
    occurrence = occ.mark_notified(make(), at=DUE)
    assert occurrence.status is OccurrenceStatus.notified
    assert occurrence.notified_at == DUE


def test_snoozed_снова_становится_notified():
    occurrence = occ.mark_notified(make(OccurrenceStatus.snoozed), at=DUE)
    assert occurrence.status is OccurrenceStatus.notified


def test_снуз_сдвигает_время_и_считает_попытки():
    occurrence = occ.snooze(make(OccurrenceStatus.notified), at=DUE)
    assert occurrence.status is OccurrenceStatus.snoozed
    assert occurrence.current_due_at == DUE + timedelta(minutes=5)
    assert occurrence.snooze_count == 1


def test_снуз_считает_пять_минут_от_нажатия_а_не_от_старого_времени():
    """Человек отреагировал через двадцать минут — напомнить надо через пять,
    а не мгновенно."""
    late = DUE + timedelta(minutes=20)
    occurrence = occ.snooze(make(OccurrenceStatus.notified), at=late)
    assert occurrence.current_due_at == late + timedelta(minutes=5)


def test_снуз_разрешает_новый_догоняющий_пинг():
    occurrence = make(OccurrenceStatus.notified, followup_sent_at=DUE)
    occ.snooze(occurrence, at=DUE)
    assert occurrence.followup_sent_at is None


def test_шестой_снуз_запрещён():
    occurrence = make(OccurrenceStatus.notified, snooze_count=MAX_SNOOZE_COUNT)
    with pytest.raises(SnoozeLimitReached):
        occ.snooze(occurrence, at=DUE)
    assert occurrence.status is OccurrenceStatus.notified


def test_кнопка_снуза_прячется_на_пятом():
    assert occ.can_snooze(make(OccurrenceStatus.notified, snooze_count=4))
    assert not occ.can_snooze(make(OccurrenceStatus.notified, snooze_count=5))
    assert not occ.can_snooze(make(OccurrenceStatus.pending))


def test_начал_и_выполнил():
    occurrence = make(OccurrenceStatus.notified)
    occ.start(occurrence, at=DUE)
    assert occurrence.status is OccurrenceStatus.in_progress
    assert occurrence.started_at == DUE

    finish = DUE + timedelta(minutes=30)
    occ.complete(occurrence, at=finish)
    assert occurrence.status is OccurrenceStatus.done
    assert occurrence.finished_at == finish


def test_выполнил_прямо_из_notified():
    """§5: догоняющий пинг тому, кто не отреагировал, тоже даёт «Выполнил»."""
    occurrence = occ.complete(make(OccurrenceStatus.notified), at=DUE)
    assert occurrence.status is OccurrenceStatus.done
    # «Начал» никто не нажимал — время начала не выдумываем.
    assert occurrence.started_at is None


def test_не_получилось_из_in_progress_даёт_skipped():
    """§5: осознанный ответ пользователя — это skipped, а не missed."""
    occurrence = occ.skip(make(OccurrenceStatus.in_progress, started_at=DUE), at=DUE)
    assert occurrence.status is OccurrenceStatus.skipped


def test_повторное_нажатие_отличается_от_запрещённого_перехода():
    done = make(OccurrenceStatus.done, finished_at=DUE)
    with pytest.raises(AlreadyInStatus):
        occ.complete(done, at=DUE)

    with pytest.raises(InvalidTransition) as info:
        occ.complete(make(OccurrenceStatus.pending), at=DUE)
    assert not isinstance(info.value, AlreadyInStatus)


def test_ночной_джоб_закрывает_только_незавершённое():
    for status in occ.UNRESOLVED_STATUSES:
        assert occ.mark_missed(make(status), at=DUE).status is OccurrenceStatus.missed

    # Пауза не пропуск: приостановленный день просто не считается (§7).
    with pytest.raises(InvalidTransition):
        occ.mark_missed(make(OccurrenceStatus.paused), at=DUE)
    with pytest.raises(InvalidTransition):
        occ.mark_missed(make(OccurrenceStatus.done), at=DUE)


def test_отметка_пинга_не_перезаписывается():
    """Инвариант 7: перезапуск джоба не должен слать пинг второй раз."""
    occurrence = make(OccurrenceStatus.notified)
    occ.mark_followup_sent(occurrence, at=DUE)
    occ.mark_followup_sent(occurrence, at=DUE + timedelta(hours=1))
    assert occurrence.followup_sent_at == DUE


def test_пауза_и_снятие_паузы():
    occurrence = make(OccurrenceStatus.pending)
    occ.pause_occurrence(occurrence)
    assert occurrence.status is OccurrenceStatus.paused
    occ.resume_occurrence(occurrence)
    assert occurrence.status is OccurrenceStatus.pending

    # На паузу можно поставить только то, что ещё не началось.
    with pytest.raises(InvalidTransition):
        occ.pause_occurrence(make(OccurrenceStatus.notified))


def test_naive_время_отвергается():
    """Инвариант 2: naive datetime молча считается временем хоста."""
    with pytest.raises(ValidationError):
        occ.mark_notified(make(), at=datetime(2026, 8, 25, 19, 0))
