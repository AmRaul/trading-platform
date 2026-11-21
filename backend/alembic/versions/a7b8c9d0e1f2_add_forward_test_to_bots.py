"""bots.forward_test — комплект бумажного форвард-теста ("portfolio/short" и т.п.)

Разметка существующих бумажных ботов — по названию, один раз (app/domain/forward_test.py).
Дальше комплект хранится у бота, и переименование разбор не ломает.

Revision ID: a7b8c9d0e1f2
Revises: e6f7a8b9c0d1
Create Date: 2026-11-21 12:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'a7b8c9d0e1f2'
down_revision: Union[str, None] = 'e6f7a8b9c0d1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Те же правила, что app.domain.forward_test.from_bot_name — продублированы, чтобы
# миграция не зависела от кода приложения, который потом может измениться
RULES = [
    ("MRC DCA · BTC 15m Long · Консервативный%", "portfolio/mrc"),
    ("Шорт альтов · пирамидинг · 5 монет · Консервативный%", "portfolio/short"),
    ("Шорт альтов · пирамидинг · 5 монет · Тейк 6%%", "take6/short"),
]


def upgrade() -> None:
    op.add_column('bots', sa.Column('forward_test', sa.String(), nullable=True))
    bots = sa.table('bots', sa.column('name', sa.String), sa.column('exchange', sa.String),
                    sa.column('forward_test', sa.String))
    for pattern, value in RULES:
        op.execute(bots.update()
                   .where(sa.and_(bots.c.exchange == 'paper', bots.c.name.like(pattern)))
                   .values(forward_test=value))


def downgrade() -> None:
    op.drop_column('bots', 'forward_test')
