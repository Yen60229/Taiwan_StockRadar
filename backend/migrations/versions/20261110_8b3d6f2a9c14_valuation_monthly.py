"""valuation_monthly: 每月 PB 快照（跟自己歷史比用）

每檔每月一筆（該月最新一天的 PB）。建表後從現有 valuations 補一次，
之後由 upsert_valuations 寫入估值時一併更新。

Revision ID: 8b3d6f2a9c14
Revises: 5c1e8a9d2f47
Create Date: 2026-11-10

"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '8b3d6f2a9c14'
down_revision: Union[str, None] = '5c1e8a9d2f47'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "valuation_monthly",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("stock_code", sa.String(10), nullable=False),
        sa.Column("month", sa.Date(), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("pb_ratio", sa.Numeric(8, 2), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("stock_code", "month", name="uq_valuation_monthly"),
    )
    # 從已有的每日估值補出每月快照：每檔每月取最新一天
    op.execute("""
        INSERT INTO valuation_monthly (stock_code, month, trade_date, pb_ratio)
        SELECT DISTINCT ON (stock_code, date_trunc('month', trade_date))
               stock_code, date_trunc('month', trade_date)::date, trade_date, pb_ratio
        FROM valuations
        WHERE pb_ratio IS NOT NULL
        ORDER BY stock_code, date_trunc('month', trade_date), trade_date DESC
    """)


def downgrade() -> None:
    op.drop_table("valuation_monthly")
