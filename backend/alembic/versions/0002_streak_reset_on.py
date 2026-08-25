"""habits.streak_reset_on

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-25

Отметка «считать текущую серию с этой даты». Нужна §8: восстановление привычки
из архива обнуляет серию, а прошлые done остаются в occurrences и без такой
отметки продолжили бы её. Рекорд считается по всей истории и отметку игнорирует.

Nullable без значения по умолчанию: у существующих привычек обнулений не было,
NULL здесь честно означает «серия считается с самого начала истории».
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '0002'
down_revision: Union[str, None] = '0001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('habits', sa.Column('streak_reset_on', sa.Date(), nullable=True))


def downgrade() -> None:
    op.drop_column('habits', 'streak_reset_on')
