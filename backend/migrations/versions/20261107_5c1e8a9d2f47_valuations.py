"""valuations: 本益比、殖利率、股價淨值比

交易所每日公布的估值表，一檔一天一筆。
PB 評級不存表，查詢時依當天資料計算（見 api/valuation.py）。

Revision ID: 5c1e8a9d2f47
Revises: 36ec7b7dceb2
Create Date: 2026-11-07

"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '5c1e8a9d2f47'
down_revision: Union[str, None] = '36ec7b7dceb2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "valuations",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("stock_code", sa.String(10), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("pe_ratio", sa.Numeric(10, 2), nullable=True),
        sa.Column("pb_ratio", sa.Numeric(8, 2), nullable=True),
        sa.Column("dividend_yield", sa.Numeric(6, 2), nullable=True),
        sa.Column("bvps", sa.Numeric(10, 2), nullable=True),
        sa.Column("fin_period", sa.String(8), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("stock_code", "trade_date", name="uq_valuations"),
    )
    op.create_index("ix_valuations_trade_date", "valuations", ["trade_date"])


def downgrade() -> None:
    op.drop_index("ix_valuations_trade_date", table_name="valuations")
    op.drop_table("valuations")
