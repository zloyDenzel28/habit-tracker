import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.habit import Habit


class HabitPause(Base):
    """Пауза по привычке.

    Инвариант 8: создаётся только по явному действию пользователя. Ни архивация,
    ни отсутствие активности, ни сбой отправки уведомлений паузу не создают.
    """

    __tablename__ = "habit_pauses"
    __table_args__ = (CheckConstraint("ends_on >= starts_on", name="dates_order"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    habit_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("habits.id", ondelete="CASCADE"), nullable=False, index=True
    )
    starts_on: Mapped[date] = mapped_column(Date, nullable=False)
    # Обязательна намеренно: бессрочная пауза даёт мёртвые привычки
    # с формально живым стриком.
    ends_on: Mapped[date] = mapped_column(Date, nullable=False)
    # Досрочное снятие паузы.
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    habit: Mapped["Habit"] = relationship(back_populates="pauses")
