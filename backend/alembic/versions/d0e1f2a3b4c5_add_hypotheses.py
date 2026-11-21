"""hypotheses — журнал гипотез с защитой от подгонки (MCP)

Revision ID: d0e1f2a3b4c5
Revises: c9d0e1f2a3b4
Create Date: 2026-11-21 16:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'd0e1f2a3b4c5'
down_revision: Union[str, None] = 'c9d0e1f2a3b4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'hypotheses',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('title', sa.String(), nullable=False),
        sa.Column('rationale', sa.Text(), nullable=True),
        sa.Column('success_criterion', sa.Text(), nullable=False),
        sa.Column('base', sa.String(), nullable=False),
        sa.Column('changes', sa.JSON(), nullable=False),
        sa.Column('idea_key', sa.String(), nullable=False),
        sa.Column('attempt', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('status', sa.String(), nullable=False, server_default='running'),
        sa.Column('task_id', sa.String(), nullable=True),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('result', sa.JSON(), nullable=True),
        sa.Column('train_decision', sa.String(), nullable=True),
        sa.Column('decision_note', sa.Text(), nullable=True),
        sa.Column('verdict', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('revealed_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_hypotheses_id', 'hypotheses', ['id'])
    op.create_index('ix_hypotheses_user_id', 'hypotheses', ['user_id'])
    op.create_index('ix_hypotheses_idea_key', 'hypotheses', ['idea_key'])
    op.create_index('ix_hypotheses_created_at', 'hypotheses', ['created_at'])


def downgrade() -> None:
    op.drop_table('hypotheses')
