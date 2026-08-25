import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.models.enums import OccurrenceStatus

if TYPE_CHECKING:
    from app.models.habit import Habit
    from app.models.user import User


class Occurrence(Base):
    """Конкретное выполнение привычки в конкретный день.

    Вся история, статусы и статистика живут здесь, а не в Habit.
    """

    __tablename__ = "occurrences"
    __table_args__ = (
        # Инвариант 7: защита от дублей при повторном запуске генератора.
        UniqueConstraint("habit_id", "scheduled_at"),
        CheckConstraint("snooze_count BETWEEN 0 AND 5", name="snooze_count_range"),
        CheckConstraint("duration_minutes >= 5", name="duration_min_5"),
        # Под запрос диспетчера уведомлений (§6.2), раз в минуту.
        Index("ix_occurrences_status_current_due_at", "status", "current_due_at"),
        # Под календарь-heatmap и расчёт стриков (§7).
        Index("ix_occurrences_user_id_local_date", "user_id", "local_date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    habit_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("habits.id", ondelete="CASCADE"), nullable=False
    )
    # Денормализация ради запросов статистики: иначе каждый heatmap — join.
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # Дата по таймзоне пользователя. Фиксирует день, в который событие реально
    # произошло, и не меняется при смене таймзоны.
    local_date: Mapped[date] = mapped_column(Date, nullable=False)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # Плановое время с учётом снузов. Догоняющий пинг считается от него,
    # поэтому снуз автоматически сдвигает и пинг.
    current_due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # Снимок длительности на момент создания occurrence. Если брать её из Habit,
    # правка привычки днём сдвинет таймер уже запущенного выполнения и перепишет
    # прошлую историю — а по §8 текущие occurrences не трогаются.
    duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[OccurrenceStatus] = mapped_column(
        Enum(OccurrenceStatus, name="occurrence_status"),
        nullable=False,
        server_default=text("'pending'"),
    )
    snooze_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Инвариант 7: защита от повторной отправки догоняющего пинга.
    followup_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    habit: Mapped["Habit"] = relationship(back_populates="occurrences")
    user: Mapped["User"] = relationship(back_populates="occurrences")
