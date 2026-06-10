"""add_user_id_to_bots

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-06-10 22:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('bots', sa.Column('user_id', sa.Integer(), nullable=True))
    op.create_index('ix_bots_user_id', 'bots', ['user_id'])
    op.create_foreign_key('fk_bots_user_id', 'bots', 'users', ['user_id'], ['id'])


def downgrade() -> None:
    op.drop_constraint('fk_bots_user_id', 'bots', type_='foreignkey')
    op.drop_index('ix_bots_user_id', table_name='bots')
    op.drop_column('bots', 'user_id')
