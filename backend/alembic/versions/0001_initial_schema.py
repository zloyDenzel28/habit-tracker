"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-08-25

Первая миграция: users, habits, occurrences, habit_pauses и тип occurrence_status.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '0001'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Статусы из §4 спеки. Имена менять нельзя.
OCCURRENCE_STATUSES = (
    'pending', 'notified', 'snoozed', 'in_progress',
    'done', 'skipped', 'missed', 'paused',
)


def upgrade() -> None:
    # Тип создаём явно и до таблиц. checkfirst делает повторный прогон
    # безопасным, если предыдущий упал на середине.
    occurrence_status = postgresql.ENUM(*OCCURRENCE_STATUSES, name='occurrence_status')
    occurrence_status.create(op.get_bind(), checkfirst=True)

    op.create_table(
        'users',
        sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('telegram_id', sa.BigInteger(), nullable=False),
        sa.Column('telegram_username', sa.String(length=64), nullable=True),
        sa.Column('first_name', sa.String(length=128), nullable=False),
        sa.Column('timezone', sa.String(length=64), server_default=sa.text("'UTC'"), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_users')),
        sa.UniqueConstraint('telegram_id', name=op.f('uq_users_telegram_id')),
    )

    op.create_table(
        'habits',
        sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('user_id', sa.UUID(), nullable=False),
        sa.Column('title', sa.String(length=200), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('duration_minutes', sa.Integer(), server_default=sa.text('5'), nullable=False),
        sa.Column('schedule_days', postgresql.ARRAY(sa.SmallInteger()), nullable=False),
        sa.Column('schedule_time', sa.Time(), nullable=False),
        sa.Column('is_archived', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint('array_length(schedule_days, 1) BETWEEN 1 AND 7', name=op.f('ck_habits_schedule_days_not_empty')),
        sa.CheckConstraint('duration_minutes >= 5', name=op.f('ck_habits_duration_min_5')),
        sa.CheckConstraint('schedule_days <@ ARRAY[1,2,3,4,5,6,7]::smallint[]', name=op.f('ck_habits_schedule_days_range')),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_habits_user_id_users'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_habits')),
    )
    op.create_index(op.f('ix_habits_is_archived'), 'habits', ['is_archived'], unique=False)
    op.create_index(op.f('ix_habits_user_id'), 'habits', ['user_id'], unique=False)

    op.create_table(
        'habit_pauses',
        sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('habit_id', sa.UUID(), nullable=False),
        sa.Column('starts_on', sa.Date(), nullable=False),
        sa.Column('ends_on', sa.Date(), nullable=False),
        sa.Column('cancelled_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint('ends_on >= starts_on', name=op.f('ck_habit_pauses_dates_order')),
        sa.ForeignKeyConstraint(['habit_id'], ['habits.id'], name=op.f('fk_habit_pauses_habit_id_habits'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_habit_pauses')),
    )
    op.create_index(op.f('ix_habit_pauses_habit_id'), 'habit_pauses', ['habit_id'], unique=False)

    op.create_table(
        'occurrences',
        sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('habit_id', sa.UUID(), nullable=False),
        sa.Column('user_id', sa.UUID(), nullable=False),
        sa.Column('local_date', sa.Date(), nullable=False),
        sa.Column('scheduled_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('current_due_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('duration_minutes', sa.Integer(), nullable=False),
        # create_type=False: тип уже создан выше, второй раз его создавать не надо.
        sa.Column(
            'status',
            postgresql.ENUM(*OCCURRENCE_STATUSES, name='occurrence_status', create_type=False),
            server_default=sa.text("'pending'"),
            nullable=False,
        ),
        sa.Column('snooze_count', sa.Integer(), server_default=sa.text('0'), nullable=False),
        sa.Column('notified_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('followup_sent_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint('duration_minutes >= 5', name=op.f('ck_occurrences_duration_min_5')),
        sa.CheckConstraint('snooze_count BETWEEN 0 AND 5', name=op.f('ck_occurrences_snooze_count_range')),
        sa.ForeignKeyConstraint(['habit_id'], ['habits.id'], name=op.f('fk_occurrences_habit_id_habits'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_occurrences_user_id_users'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_occurrences')),
        # Инвариант 7: защита от дублей при повторном запуске генератора.
        sa.UniqueConstraint('habit_id', 'scheduled_at', name=op.f('uq_occurrences_habit_id_scheduled_at')),
    )
    op.create_index('ix_occurrences_status_current_due_at', 'occurrences', ['status', 'current_due_at'], unique=False)
    op.create_index('ix_occurrences_user_id_local_date', 'occurrences', ['user_id', 'local_date'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_occurrences_user_id_local_date', table_name='occurrences')
    op.drop_index('ix_occurrences_status_current_due_at', table_name='occurrences')
    op.drop_table('occurrences')
    op.drop_index(op.f('ix_habit_pauses_habit_id'), table_name='habit_pauses')
    op.drop_table('habit_pauses')
    op.drop_index(op.f('ix_habits_user_id'), table_name='habits')
    op.drop_index(op.f('ix_habits_is_archived'), table_name='habits')
    op.drop_table('habits')
    op.drop_table('users')
    # drop_table не удаляет нативный PG-тип. Без этой строки повторный upgrade
    # упадёт с "type occurrence_status already exists".
    postgresql.ENUM(name='occurrence_status').drop(op.get_bind(), checkfirst=True)
