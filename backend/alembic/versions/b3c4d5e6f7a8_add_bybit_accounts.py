"""add bybit_accounts, bots.exchange, bots.bybit_account_id

Revision ID: b3c4d5e6f7a8
Revises: a1b2c3d4e5f7
Create Date: 2026-08-31

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = 'b3c4d5e6f7a8'
down_revision: Union[str, None] = 'a1b2c3d4e5f7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'bybit_accounts',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('api_key', sa.String(), nullable=False),
        sa.Column('api_secret', sa.String(), nullable=False),
        sa.Column('testnet', sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_bybit_accounts_id', 'bybit_accounts', ['id'])
    op.create_index('ix_bybit_accounts_user_id', 'bybit_accounts', ['user_id'])

    # server_default required — bots table already has rows, all existing
    # bots trade through Cryptorg today so 'cryptorg' is the correct default.
    op.add_column('bots', sa.Column('exchange', sa.String(), server_default='cryptorg', nullable=False))
    op.add_column('bots', sa.Column('bybit_account_id', sa.Integer(), sa.ForeignKey('bybit_accounts.id'), nullable=True))


def downgrade() -> None:
    op.drop_column('bots', 'bybit_account_id')
    op.drop_column('bots', 'exchange')

    op.drop_index('ix_bybit_accounts_user_id', table_name='bybit_accounts')
    op.drop_index('ix_bybit_accounts_id', table_name='bybit_accounts')
    op.drop_table('bybit_accounts')
