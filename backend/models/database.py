"""
StockRadar - Database Models & Connection
PostgreSQL + SQLAlchemy (async)
"""
import os
from datetime import datetime

from sqlalchemy import (
    BigInteger, Boolean, CheckConstraint, Column, Date, DateTime, ForeignKey,
    Integer, Numeric, String, UniqueConstraint, text
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

# ── 連線設定 ──────────────────────────────────────────────────
DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+asyncpg://postgres:password@localhost:5432/stockradar"
).replace("postgresql://", "postgresql+asyncpg://")  # Railway 相容

engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    pool_size=5,
    max_overflow=10,
    pool_pre_ping=True,
)

AsyncSessionLocal = sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)

async def get_db():
    async with AsyncSessionLocal() as session:
        yield session


# ── Base ──────────────────────────────────────────────────────
class Base(DeclarativeBase):
    pass


# ── 股票基本資料（靜態，季度更新） ──────────────────────────────
class Stock(Base):
    __tablename__ = "stocks"

    code        = Column(String(10),  primary_key=True)       # 股票代號
    name        = Column(String(50),  nullable=False)          # 公司全名
    short_name  = Column(String(20),  nullable=True)           # 市場簡稱（台積電、富邦金）
    market      = Column(String(4),   nullable=False, index=True)  # TWSE / TPEX
    industry    = Column(String(30),  nullable=True,  index=True)  # 產業類別
    isin        = Column(String(20),  nullable=True)
    list_date   = Column(Date,        nullable=True)            # 上市日期
    updated_at  = Column(DateTime,    default=datetime.utcnow, onupdate=datetime.utcnow)


# ── 每日行情（時序主表） ──────────────────────────────────────
class DailyQuote(Base):
    __tablename__ = "daily_quotes"

    id          = Column(BigInteger,  primary_key=True, autoincrement=True)
    stock_code  = Column(String(10),  nullable=False, index=True)  # FK -> stocks.code
    trade_date  = Column(Date,        nullable=False, index=True)
    open        = Column(Numeric(10, 2), nullable=True)
    high        = Column(Numeric(10, 2), nullable=True)
    low         = Column(Numeric(10, 2), nullable=True)
    close       = Column(Numeric(10, 2), nullable=True)
    volume      = Column(BigInteger,  nullable=True)               # 成交量（張）
    avg_vol_20d = Column(Numeric(12, 1), nullable=True)            # 20日均量（張）
    created_at  = Column(DateTime,    default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("stock_code", "trade_date", name="uq_daily_quotes"),
    )


# ── 三大法人買賣超 ────────────────────────────────────────────
class InstitutionalFlow(Base):
    __tablename__ = "institutional_flow"

    id          = Column(BigInteger,  primary_key=True, autoincrement=True)
    stock_code  = Column(String(10),  nullable=False, index=True)
    trade_date  = Column(Date,        nullable=False, index=True)
    foreign_net = Column(BigInteger,  nullable=True)   # 外資買賣超（張）
    trust_net   = Column(BigInteger,  nullable=True)   # 投信買賣超（張）
    dealer_net  = Column(BigInteger,  nullable=True)   # 自營商買賣超（張）
    total_net   = Column(BigInteger,  nullable=True)   # 三大合計

    __table_args__ = (
        UniqueConstraint("stock_code", "trade_date", name="uq_inst_flow"),
    )


# ── 籌碼集中度（集保週資料） ──────────────────────────────────
class ChipConcentration(Base):
    __tablename__ = "chip_concentration"

    id              = Column(BigInteger,    primary_key=True, autoincrement=True)
    stock_code      = Column(String(10),    nullable=False, index=True)
    week_date       = Column(Date,          nullable=False, index=True)  # 集保公告週（週五）
    holders_400up   = Column(Integer,       nullable=True)   # 400張以上持股人數
    holders_total   = Column(Integer,       nullable=True)   # 總持股人數
    shares_400up    = Column(BigInteger,    nullable=True)   # 400張以上持股張數
    conc_ratio      = Column(Numeric(5, 2), nullable=True, index=True)  # 集中度 %

    __table_args__ = (
        UniqueConstraint("stock_code", "week_date", name="uq_chip_conc"),
    )


# ── 使用者 ────────────────────────────────────────────────────
# 角色與狀態刻意用 text + CHECK 約束，不用 PostgreSQL 的 ENUM 型別：
# ENUM 要新增一個值就得跑 ALTER TYPE，在交易裡還有限制；text + CHECK
# 一樣擋得住寫入垃圾值，要擴充時只是改一條約束，痛苦少很多。
ROLE_USER  = "user"
ROLE_ADMIN = "admin"
VALID_ROLES = (ROLE_USER, ROLE_ADMIN)

STATUS_PENDING  = "pending"    # 剛註冊，等管理員核准
STATUS_ACTIVE   = "active"     # 可以正常登入使用
STATUS_REJECTED = "rejected"   # 管理員拒絕
STATUS_DISABLED = "disabled"   # 曾經可用，被管理員停權
VALID_STATUSES = (STATUS_PENDING, STATUS_ACTIVE, STATUS_REJECTED, STATUS_DISABLED)


class User(Base):
    __tablename__ = "users"

    id           = Column(UUID(as_uuid=True), primary_key=True,
                          server_default=text("gen_random_uuid()"))
    email        = Column(String(120), nullable=False, unique=True)
    hashed_pw    = Column(String(128), nullable=False)
    name         = Column(String(50),  nullable=True)
    notify_email = Column(Boolean,     default=True)
    created_at   = Column(DateTime,    default=datetime.utcnow)

    # ── 註冊核准制 + 角色（見 docs/roadmap/06-auth-hardening.md M1）──
    role          = Column(String(16), nullable=False, server_default=ROLE_USER)
    status        = Column(String(16), nullable=False, server_default=STATUS_PENDING)
    approved_at   = Column(DateTime,   nullable=True)
    approved_by   = Column(UUID(as_uuid=True),
                           ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    last_login_at = Column(DateTime,   nullable=True)

    __table_args__ = (
        CheckConstraint(
            "role IN ('user', 'admin')", name="ck_users_role",
        ),
        CheckConstraint(
            "status IN ('pending', 'active', 'rejected', 'disabled')",
            name="ck_users_status",
        ),
    )

    @property
    def is_admin(self) -> bool:
        return self.role == ROLE_ADMIN

    @property
    def can_login(self) -> bool:
        return self.status == STATUS_ACTIVE


# ── 自選清單 ──────────────────────────────────────────────────
class Watchlist(Base):
    __tablename__ = "watchlist"

    id         = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id    = Column(UUID(as_uuid=True), nullable=False, index=True)
    stock_code = Column(String(10),         nullable=False)
    added_at   = Column(DateTime,           default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("user_id", "stock_code", name="uq_watchlist"),
    )


# ── 持股比例（外資 / 投信 / 董監，週 or 季更新） ────────────
class OwnershipRatio(Base):
    __tablename__ = "ownership_ratios"

    id                  = Column(BigInteger,    primary_key=True, autoincrement=True)
    stock_code          = Column(String(10),    nullable=False, index=True)
    report_date         = Column(Date,          nullable=False, index=True)
    foreign_hold_ratio  = Column(Numeric(6, 2), nullable=True)   # 外資持股比例 %
    trust_hold_ratio    = Column(Numeric(6, 2), nullable=True)   # 投信持股比例 %
    director_hold_ratio = Column(Numeric(6, 2), nullable=True)   # 董監事持股比例 %

    __table_args__ = (
        UniqueConstraint("stock_code", "report_date", name="uq_ownership_ratio"),
    )

# 注意：這裡刻意沒有 init_db() / create_all()。
# 唯一的建表路徑是 Alembic（見 migrations/、scripts/alembic_utils.py）：
#   dev  → docker-compose.yml 的 api command 先跑 `alembic upgrade head`
#   prod → scripts/deploy.sh 在啟動服務前跑一次
# 保留 create_all() 當第二條路會讓兩者長期漂移而不自知——
# 這正是 06-auth-hardening.md M0 要解決的事。
