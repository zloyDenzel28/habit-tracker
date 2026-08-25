"""Правила стрика из §7. Тесты чистые: БД здесь не нужна."""

from datetime import date, timedelta

from app.models import OccurrenceStatus
from app.services.stats import compute_streaks

TODAY = date(2026, 8, 25)


def days_ago(n: int) -> date:
    return TODAY - timedelta(days=n)


def series(*items: tuple[int, OccurrenceStatus]) -> list[tuple[date, OccurrenceStatus]]:
    """(сколько дней назад, статус) -> (дата, статус)."""
    return [(days_ago(n), status) for n, status in items]


DONE = OccurrenceStatus.done
SKIPPED = OccurrenceStatus.skipped
MISSED = OccurrenceStatus.missed
PAUSED = OccurrenceStatus.paused
PENDING = OccurrenceStatus.pending


def test_пустая_история():
    result = compute_streaks([], today=TODAY)
    assert (result.current, result.best) == (0, 0)


def test_подряд_выполненные_дни_дают_серию():
    result = compute_streaks(series(*[(n, DONE) for n in range(5, 0, -1)]), today=TODAY)
    assert (result.current, result.best) == (5, 5)


def test_skipped_ломает_серию():
    result = compute_streaks(
        series((3, DONE), (2, SKIPPED), (1, DONE)), today=TODAY
    )
    assert (result.current, result.best) == (1, 1)


def test_missed_ломает_серию_так_же_как_skipped():
    with_skip = compute_streaks(series((3, DONE), (2, SKIPPED), (1, DONE)), today=TODAY)
    with_miss = compute_streaks(series((3, DONE), (2, MISSED), (1, DONE)), today=TODAY)
    assert with_skip == with_miss


def test_рекорд_помнит_прошлую_серию():
    result = compute_streaks(
        series((6, DONE), (5, DONE), (4, DONE), (3, MISSED), (2, DONE), (1, DONE)),
        today=TODAY,
    )
    assert (result.current, result.best) == (2, 3)


def test_незакрытые_статусы_не_влияют():
    """Сегодняшний день ещё в работе — он не должен ни ломать серию, ни считаться."""
    result = compute_streaks(series((2, DONE), (1, DONE), (0, PENDING)), today=TODAY)
    assert (result.current, result.best) == (2, 2)


def test_дни_паузы_не_ломают_и_не_увеличивают_серию():
    """Пример из §7: 10 дней подряд -> пауза 5 дней -> выполнено = серия 11."""
    history = (
        [(n, DONE) for n in range(20, 10, -1)]
        + [(n, PAUSED) for n in range(10, 5, -1)]
        + [(5, DONE)]
    )
    result = compute_streaks(series(*history), today=TODAY)
    assert (result.current, result.best) == (11, 11)


def test_пауза_длиннее_14_дней_обнуляет_серию_но_не_рекорд():
    """Второй пример из §7: та же ситуация с паузой 20 дней = серия 1, рекорд 10."""
    history = (
        [(n, DONE) for n in range(50, 40, -1)]
        + [(n, PAUSED) for n in range(40, 20, -1)]
        + [(20, DONE)]
    )
    # Пауза с 40 по 21 день назад, значит возобновление — за 20 дней до сегодня.
    result = compute_streaks(
        series(*history), reset_dates=[days_ago(20)], today=TODAY
    )
    assert (result.current, result.best) == (1, 10)


def test_пауза_ровно_14_дней_серию_не_обнуляет():
    history = (
        [(n, DONE) for n in range(30, 20, -1)]
        + [(n, PAUSED) for n in range(20, 6, -1)]
        + [(6, DONE)]
    )
    # 14 дней паузы — правило §7 срабатывает строго на «дольше 14».
    result = compute_streaks(series(*history), reset_dates=[], today=TODAY)
    assert (result.current, result.best) == (11, 11)


def test_запланированное_обнуление_в_будущем_игнорируется():
    """Пауза обнуляет серию при возобновлении, а не когда её только завели.

    Иначе форма заморозки не смогла бы показать «сейчас 23 дня» — серия
    обнулилась бы в момент нажатия.
    """
    history = [(n, DONE) for n in range(5, 0, -1)]
    result = compute_streaks(
        series(*history), reset_dates=[TODAY + timedelta(days=3)], today=TODAY
    )
    assert (result.current, result.best) == (5, 5)


def test_восстановление_из_архива_обнуляет_серию():
    """§8: streak_reset_on приходит сюда как обычная дата обнуления."""
    history = [(n, DONE) for n in range(10, 0, -1)]
    result = compute_streaks(
        series(*history), reset_dates=[days_ago(3)], today=TODAY
    )
    # Обнуление за 3 дня до сегодня: до него 7 дней серии (рекорд), после — 3.
    assert (result.current, result.best) == (3, 7)


def test_обнуление_после_последней_записи_сбрасывает_текущую_серию():
    """Пауза кончилась вчера, а ближайший день по расписанию ещё не наступил."""
    history = [(n, DONE) for n in range(10, 5, -1)]
    result = compute_streaks(series(*history), reset_dates=[days_ago(1)], today=TODAY)
    assert (result.current, result.best) == (0, 5)


def test_порядок_входных_данных_не_важен():
    history = series((3, DONE), (2, MISSED), (1, DONE))
    assert compute_streaks(history, today=TODAY) == compute_streaks(
        list(reversed(history)), today=TODAY
    )
