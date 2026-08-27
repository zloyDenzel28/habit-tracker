"""sent_messages

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-27

Шаг 6, находка 2: действие в вебе должно гасить сообщение в чате. Для этого
нужен message_id отправленного сообщения и его текст — Bot API не умеет ни
читать чужое сообщение по id, ни редактировать его без полного нового текста.

Отдельной таблицей, а не колонками на occurrences: по §5 снуз возвращает
занятие в выборку диспетчера и обнуляет followup_sent_at, поэтому сообщений
на одно занятие бывает до двенадцати. Колонка перезаписывалась бы, и все,
кроме последнего, остались бы в чате с живыми кнопками навсегда.

Данных не переносит: у сообщений, отправленных до этой миграции, message_id
не сохранился нигде. Они так и останутся с живыми кнопками — нажатие на них
по-прежнему отработает, а бот отредактирует сообщение сам, потому что держит
его в руках.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '0003'
down_revision: Union[str, None] = '0002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Два вида сообщений из §5.
SENT_MESSAGE_KINDS = ('notification', 'followup')


def upgrade() -> None:
    # Тип создаём явно и до таблицы — как occurrence_status в 0001.
    sent_message_kind = postgresql.ENUM(*SENT_MESSAGE_KINDS, name='sent_message_kind')
    sent_message_kind.create(op.get_bind(), checkfirst=True)

    op.create_table(
        'sent_messages',
        sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('occurrence_id', sa.UUID(), nullable=False),
        sa.Column(
            'kind',
            postgresql.ENUM(*SENT_MESSAGE_KINDS, name='sent_message_kind', create_type=False),
            nullable=False,
        ),
        sa.Column('message_id', sa.BigInteger(), nullable=False),
        # Снимок отправленного текста с HTML-разметкой.
        sa.Column('text', sa.Text(), nullable=False),
        sa.Column('sent_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('closed_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['occurrence_id'], ['occurrences.id'], name=op.f('fk_sent_messages_occurrence_id_occurrences'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_sent_messages')),
    )
    op.create_index(op.f('ix_sent_messages_occurrence_id'), 'sent_messages', ['occurrence_id'], unique=False)
    # Частичный: джоб закрытия ищет только незакрытые, а их всегда единицы.
    op.create_index(
        'ix_sent_messages_open',
        'sent_messages',
        ['occurrence_id'],
        unique=False,
        postgresql_where=sa.text('closed_at IS NULL'),
    )


def downgrade() -> None:
    op.drop_index('ix_sent_messages_open', table_name='sent_messages')
    op.drop_index(op.f('ix_sent_messages_occurrence_id'), table_name='sent_messages')
    op.drop_table('sent_messages')
    # drop_table не удаляет нативный PG-тип.
    postgresql.ENUM(name='sent_message_kind').drop(op.get_bind(), checkfirst=True)
