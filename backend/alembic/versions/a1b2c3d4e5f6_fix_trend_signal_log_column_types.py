"""fix trend_signal_log column types: trend_4h boolean -> varchar

Revision ID: a1b2c3d4e5f6
Revises: fe5e5060310c
Create Date: 2026-06-28 16:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = 'fe5e5060310c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE trend_signal_log
        ALTER COLUMN trend_4h TYPE VARCHAR
        USING CASE WHEN trend_4h THEN 'UP' ELSE 'DOWN' END
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE trend_signal_log
        ALTER COLUMN trend_4h TYPE BOOLEAN
        USING CASE WHEN trend_4h = 'UP' THEN TRUE ELSE FALSE END
    """)
