"""add limit_entry_price to bots

Revision ID: e1f2a3b4c5d6
Revises: d1e2f3a4b5c6
Create Date: 2026-06-29

"""
from typing import Union
from alembic import op
import sqlalchemy as sa

revision: str = 'e1f2a3b4c5d6'
down_revision: Union[str, None] = 'd1e2f3a4b5c6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('bots', sa.Column('limit_entry_price', sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column('bots', 'limit_entry_price')
