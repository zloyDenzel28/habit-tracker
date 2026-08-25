import uuid
from datetime import date, datetime, time
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    SmallInteger,
    String,
    Text,
    Time,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.habit_pause import HabitPause
    from app.models.occurrence import Occurrence
    from app.models.user import User


class Habit(Base):
    """Шаблон привычки. Состояние выполнения здесь не хранится — оно на Occurrence."""

    __tablename__ = "habits"
    __table_args__ = (
        CheckConstraint("duration_minutes >= 5", name="duration_min_5"),
        CheckConstraint(
            "array_length(schedule_days, 1) BETWEEN 1 AND 7", name="schedule_days_not_empty"
        ),
        CheckConstraint(
            "schedule_days <@ ARRAY[1,2,3,4,5,6,7]::smallint[]", name="schedule_days_range"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    duration_minutes: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("5")
    )
    # Дни недели 1-7 (пн-вс). Массив, а не битмаска: читается глазами в psql
    # и ищется через оператор @>.
    schedule_days: Mapped[list[int]] = mapped_column(ARRAY(SmallInteger), nullable=False)
    # Инвариант 3: локальное время пользователя БЕЗ таймзоны. Если хранить UTC,
    # переход на летнее время сдвинет расписание на час.
    schedule_time: Mapped[time] = mapped_column(Time(timezone=False), nullable=False)
    # Мягкое удаление. Восстановление из архива обнуляет текущую серию (§8).
    is_archived: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false"), index=True
    )
    # Дата, с которой считается текущая серия. Ставится при восстановлении
    # из архива (§8): прошлые done никуда не деваются, и без такой отметки
    # серия продолжилась бы, а архив работал бы как бесконечная пауза в обход
    # правила 14 дней. Рекорд считается по всей истории и отметку игнорирует.
    streak_reset_on: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    user: Mapped["User"] = relationship(back_populates="habits")
    occurrences: Mapped[list["Occurrence"]] = relationship(
        back_populates="habit", cascade="all, delete-orphan"
    )
    pauses: Mapped[list["HabitPause"]] = relationship(
        back_populates="habit", cascade="all, delete-orphan"
    )
