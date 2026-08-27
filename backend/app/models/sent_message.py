import uuid
from datetime import datetime
from typing import TYPE_CHECKING

# sa.text ниже по телу класса перекрыт колонкой text — все вызовы должны
# оставаться выше её объявления.
from sqlalchemy import BigInteger, DateTime, Enum, ForeignKey, Index, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.models.enums import SentMessageKind

if TYPE_CHECKING:
    from app.models.occurrence import Occurrence


class SentMessage(Base):
    """Одно отправленное в Telegram сообщение с живыми кнопками.

    Нужна, чтобы действие из веба гасило сообщение в чате: без message_id
    дотянуться до него не может никто, а Bot API не умеет ни читать чужое
    сообщение по id, ни редактировать его без полного нового текста.

    Отдельной таблицей, а не колонками на Occurrence: сообщений на занятие
    не два. По §5 снуз возвращает занятие в выборку диспетчера и обнуляет
    followup_sent_at, поэтому при пяти снузах уведомлений будет до шести и
    пингов до шести. Колонка перезаписалась бы, а прошлые сообщения остались
    бы в чате с живыми кнопками навсегда — закрыть их было бы нечем.
    """

    __tablename__ = "sent_messages"
    __table_args__ = (
        # Под выборку джоба закрытия: открытых строк всегда единицы, а
        # закрытых со временем становится по одной на каждое занятие.
        Index(
            "ix_sent_messages_open",
            "occurrence_id",
            postgresql_where=text("closed_at IS NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    occurrence_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("occurrences.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    kind: Mapped[SentMessageKind] = mapped_column(
        Enum(SentMessageKind, name="sent_message_kind"), nullable=False
    )
    # Telegram отдаёт message_id как int; BigInteger — запас, чтобы не
    # упереться в границу int32 на долгоживущем чате.
    message_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    # Снимок отправленного текста вместе с HTML-разметкой.
    #
    # Хранится, а не пересобирается через services/messages.py, по той же
    # причине, по которой Occurrence хранит снимок duration_minutes (§3):
    # отправленное сообщение — факт прошлого. Пересборка считала бы его от
    # текущего состояния занятия и в трёх случаях выдала бы текст, которого
    # человеку не отправляли: ветка пинга зависит от status is in_progress,
    # время в уведомлении — от current_due_at (его двигает снуз), название —
    # от привычки (её правит §8).
    text: Mapped[str] = mapped_column(Text, nullable=False)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # Кнопки убраны, итог дописан. Инвариант 7: отметка защищает от повторного
    # редактирования так же, как notified_at — от повторной отправки.
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    occurrence: Mapped["Occurrence"] = relationship()
