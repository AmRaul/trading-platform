"""add runtime_state to bots (straddle construct state)

Revision ID: c4d5e6f7a8b9
Revises: b3c4d5e6f7a8
Create Date: 2026-10-17

"""
from typing import Union
from alembic import op
import sqlalchemy as sa

revision: str = 'c4d5e6f7a8b9'
down_revision: Union[str, None] = 'b3c4d5e6f7a8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('bots', sa.Column('runtime_state', sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column('bots', 'runtime_state')
