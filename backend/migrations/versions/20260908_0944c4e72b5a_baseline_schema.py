"""baseline schema

Baseline migration mirroring the schema already produced by
`models.database.init_db()` (i.e. `Base.metadata.create_all()`), which is
what created the tables currently running in production.

This migration exists so that a *new* environment (a fresh dev machine, a
future staging DB, a disaster-recovery restore onto an empty database) can
run `alembic upgrade head` instead of relying on the app calling
`create_all()` at startup -- which `main.py` explicitly skips when
APP_ENV=production (see api/main.py lifespan).

Column types, nullability, unique constraints and index names below were
generated directly from `Base.metadata` via SQLAlchemy's DDL compiler
against the postgresql dialect, not hand-typed, so they match the live
schema exactly (see docs/roadmap/06-auth-hardening.md, milestone M0).

Revision ID: 0944c4e72b5a
Revises:
Create Date: 2026-09-08 23:30:09.987229

"""
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '0944c4e72b5a'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── stocks ────────────────────────────────────────────────
    op.create_table(
        "stocks",
        sa.Column("code", sa.String(10), primary_key=True),
        sa.Column("name", sa.String(50), nullable=False),
        sa.Column("short_name", sa.String(20), nullable=True),
        sa.Column("market", sa.String(4), nullable=False),
        sa.Column("industry", sa.String(30), nullable=True),
        sa.Column("isin", sa.String(20), nullable=True),
        sa.Column("list_date", sa.Date(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_stocks_market", "stocks", ["market"])
    op.create_index("ix_stocks_industry", "stocks", ["industry"])

    # ── daily_quotes ──────────────────────────────────────────
    op.create_table(
        "daily_quotes",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("stock_code", sa.String(10), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("open", sa.Numeric(10, 2), nullable=True),
        sa.Column("high", sa.Numeric(10, 2), nullable=True),
        sa.Column("low", sa.Numeric(10, 2), nullable=True),
        sa.Column("close", sa.Numeric(10, 2), nullable=True),
        sa.Column("volume", sa.BigInteger(), nullable=True),
        sa.Column("avg_vol_20d", sa.Numeric(12, 1), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("stock_code", "trade_date", name="uq_daily_quotes"),
    )
    op.create_index("ix_daily_quotes_stock_code", "daily_quotes", ["stock_code"])
    op.create_index("ix_daily_quotes_trade_date", "daily_quotes", ["trade_date"])

    # ── institutional_flow ────────────────────────────────────
    op.create_table(
        "institutional_flow",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("stock_code", sa.String(10), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("foreign_net", sa.BigInteger(), nullable=True),
        sa.Column("trust_net", sa.BigInteger(), nullable=True),
        sa.Column("dealer_net", sa.BigInteger(), nullable=True),
        sa.Column("total_net", sa.BigInteger(), nullable=True),
        sa.UniqueConstraint("stock_code", "trade_date", name="uq_inst_flow"),
    )
    op.create_index("ix_institutional_flow_stock_code", "institutional_flow", ["stock_code"])
    op.create_index("ix_institutional_flow_trade_date", "institutional_flow", ["trade_date"])

    # ── chip_concentration ────────────────────────────────────
    op.create_table(
        "chip_concentration",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("stock_code", sa.String(10), nullable=False),
        sa.Column("week_date", sa.Date(), nullable=False),
        sa.Column("holders_400up", sa.Integer(), nullable=True),
        sa.Column("holders_total", sa.Integer(), nullable=True),
        sa.Column("shares_400up", sa.BigInteger(), nullable=True),
        sa.Column("conc_ratio", sa.Numeric(5, 2), nullable=True),
        sa.UniqueConstraint("stock_code", "week_date", name="uq_chip_conc"),
    )
    op.create_index("ix_chip_concentration_stock_code", "chip_concentration", ["stock_code"])
    op.create_index("ix_chip_concentration_week_date", "chip_concentration", ["week_date"])
    op.create_index("ix_chip_concentration_conc_ratio", "chip_concentration", ["conc_ratio"])

    # ── users ─────────────────────────────────────────────────
    op.create_table(
        "users",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column("email", sa.String(120), nullable=False, unique=True),
        sa.Column("hashed_pw", sa.String(128), nullable=False),
        sa.Column("name", sa.String(50), nullable=True),
        sa.Column("notify_email", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )

    # ── watchlist ─────────────────────────────────────────────
    op.create_table(
        "watchlist",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("stock_code", sa.String(10), nullable=False),
        sa.Column("added_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("user_id", "stock_code", name="uq_watchlist"),
    )
    op.create_index("ix_watchlist_user_id", "watchlist", ["user_id"])

    # ── ownership_ratios ──────────────────────────────────────
    op.create_table(
        "ownership_ratios",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("stock_code", sa.String(10), nullable=False),
        sa.Column("report_date", sa.Date(), nullable=False),
        sa.Column("foreign_hold_ratio", sa.Numeric(6, 2), nullable=True),
        sa.Column("trust_hold_ratio", sa.Numeric(6, 2), nullable=True),
        sa.Column("director_hold_ratio", sa.Numeric(6, 2), nullable=True),
        sa.UniqueConstraint("stock_code", "report_date", name="uq_ownership_ratio"),
    )
    op.create_index("ix_ownership_ratios_stock_code", "ownership_ratios", ["stock_code"])
    op.create_index("ix_ownership_ratios_report_date", "ownership_ratios", ["report_date"])


def downgrade() -> None:
    op.drop_table("ownership_ratios")
    op.drop_table("watchlist")
    op.drop_table("users")
    op.drop_table("chip_concentration")
    op.drop_table("institutional_flow")
    op.drop_table("daily_quotes")
    op.drop_table("stocks")
