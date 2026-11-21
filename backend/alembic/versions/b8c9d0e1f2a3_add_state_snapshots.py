"""state_snapshots — снимки состояния ботов для what_changed (MCP)

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
Create Date: 2026-11-21 12:10:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'b8c9d0e1f2a3'
down_revision: Union[str, None] = 'a7b8c9d0e1f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'state_snapshots',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('taken_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('data', sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_state_snapshots_id', 'state_snapshots', ['id'])
    op.create_index('ix_state_snapshots_user_id', 'state_snapshots', ['user_id'])
    op.create_index('ix_state_snapshots_taken_at', 'state_snapshots', ['taken_at'])


def downgrade() -> None:
    op.drop_table('state_snapshots')
