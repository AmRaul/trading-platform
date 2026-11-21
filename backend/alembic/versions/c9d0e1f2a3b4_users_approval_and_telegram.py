"""users: одобрение регистрации и личный Telegram

- approved — заявка одобрена админом (новые регистрации ждут одобрения);
  уже существующие пользователи считаются одобренными;
- telegram_chat_id / telegram_notify — личный чат для уведомлений и алертов;
- telegram_link_code / telegram_link_expires — одноразовый код привязки (/start <код> боту).

Revision ID: c9d0e1f2a3b4
Revises: b8c9d0e1f2a3
Create Date: 2026-11-21 14:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'c9d0e1f2a3b4'
down_revision: Union[str, None] = 'b8c9d0e1f2a3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('users', sa.Column('approved', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.execute("update users set approved = true")
    op.add_column('users', sa.Column('telegram_chat_id', sa.String(), nullable=True))
    op.add_column('users', sa.Column('telegram_notify', sa.String(), nullable=False, server_default='all'))
    op.add_column('users', sa.Column('telegram_link_code', sa.String(), nullable=True))
    op.add_column('users', sa.Column('telegram_link_expires', sa.DateTime(timezone=True), nullable=True))
    op.create_index('ix_users_telegram_link_code', 'users', ['telegram_link_code'], unique=True)


def downgrade() -> None:
    op.drop_index('ix_users_telegram_link_code', 'users')
    for col in ('telegram_link_expires', 'telegram_link_code', 'telegram_notify', 'telegram_chat_id', 'approved'):
        op.drop_column('users', col)
