"""add cryptorg_accounts, remove user_credentials

Revision ID: d1e2f3a4b5c6
Revises: c3d4e5f6a7b8
Create Date: 2026-06-28 18:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = 'd1e2f3a4b5c6'
down_revision: Union[str, None] = 'c3d4e5f6a7b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'cryptorg_accounts',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('webhook_url', sa.String(), nullable=False),
        sa.Column('api_key', sa.String(), nullable=True),
        sa.Column('api_secret', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_cryptorg_accounts_id', 'cryptorg_accounts', ['id'])
    op.create_index('ix_cryptorg_accounts_user_id', 'cryptorg_accounts', ['user_id'])

    op.add_column('bots', sa.Column('account_id', sa.Integer(), sa.ForeignKey('cryptorg_accounts.id'), nullable=True))

    op.drop_table('user_credentials')


def downgrade() -> None:
    op.drop_column('bots', 'account_id')
    op.drop_index('ix_cryptorg_accounts_user_id', table_name='cryptorg_accounts')
    op.drop_index('ix_cryptorg_accounts_id', table_name='cryptorg_accounts')
    op.drop_table('cryptorg_accounts')

    op.create_table(
        'user_credentials',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('exchange', sa.String(), nullable=True),
        sa.Column('webhook_url', sa.String(), nullable=False),
        sa.Column('api_key', sa.String(), nullable=True),
        sa.Column('api_secret', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id'),
    )
