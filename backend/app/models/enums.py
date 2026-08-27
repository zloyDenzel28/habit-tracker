import enum


class SentMessageKind(str, enum.Enum):
    """Что за сообщение мы отправили в чат — оба вида описаны в §5.

    Различать нужно ровно для того, чтобы отличить первое уведомление от
    догоняющего пинга в логах и выборках: сам текст лежит снимком рядом,
    и пересобирать его по виду не приходится.
    """

    notification = "notification"
    followup = "followup"


class OccurrenceStatus(str, enum.Enum):
    """Статусы из §4 спеки. Имена менять нельзя.

    Имена членов намеренно совпадают со значениями: SQLAlchemy пишет в
    нативный PG-тип имя члена, так что в БД лежит ровно то, что в документе.
    """

    pending = "pending"
    notified = "notified"
    snoozed = "snoozed"
    in_progress = "in_progress"
    done = "done"
    skipped = "skipped"
    missed = "missed"
    paused = "paused"


# В §4 спеки paused перечислен среди терминальных, но там же есть переход
# paused -> pending при снятии паузы. Терминальным он быть не может —
# считаем терминальными только три статуса, из которых выхода нет.
TERMINAL_STATUSES: frozenset[OccurrenceStatus] = frozenset(
    {OccurrenceStatus.done, OccurrenceStatus.skipped, OccurrenceStatus.missed}
)

MAX_SNOOZE_COUNT = 5
