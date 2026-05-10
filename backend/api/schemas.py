"""
StockRadar - Pydantic Schemas
所有 API 進出資料的驗證模型
"""
from datetime import date, datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, ConfigDict


# ── Auth ──────────────────────────────────────────────────────
class UserRegister(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=6, max_length=64)
    name: Optional[str] = None


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: "UserOut"


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    email: EmailStr
    name: Optional[str] = None
    notify_email: bool = True


# ── Screen ────────────────────────────────────────────────────
class ScreenFilter(BaseModel):
    """篩選參數"""
    min_avg_vol: int    = Field(2000, ge=0,    description="日均量門檻（張）")
    min_conc:    float  = Field(40.0, ge=0,    le=100, description="集中度門檻 %")
    industries:  Optional[list[str]] = None    # 產業類別過濾
    markets:     Optional[list[str]] = None    # ["TWSE", "TPEX"]
    only_inst_buy: bool = False                # 只顯示三大法人買超


class ScreenItem(BaseModel):
    """單一篩選結果列"""
    model_config = ConfigDict(from_attributes=True)
    code:        str
    name:        str
    short_name:  Optional[str] = None
    market:      str
    industry:    Optional[str] = None
    close:       Optional[Decimal] = None
    volume:      Optional[int] = None
    avg_vol_20d: Optional[Decimal] = None
    conc_ratio:  Optional[Decimal] = None
    foreign_net: Optional[int] = None
    trust_net:   Optional[int] = None
    dealer_net:  Optional[int] = None
    total_net:   Optional[int] = None
    # 持股比例
    foreign_hold_ratio:  Optional[Decimal] = None   # 外資持股比例 %
    trust_hold_ratio:    Optional[Decimal] = None   # 投信持股比例 %
    director_hold_ratio: Optional[Decimal] = None   # 董監事持股比例 %
    in_watchlist: bool = False


class ScreenResponse(BaseModel):
    total:  int
    items:  list[ScreenItem]
    filters: ScreenFilter
    last_update: Optional[datetime] = None


# ── Stock detail ──────────────────────────────────────────────
class InstFlowPoint(BaseModel):
    trade_date:  date
    foreign_net: Optional[int] = None
    trust_net:   Optional[int] = None
    dealer_net:  Optional[int] = None
    total_net:   Optional[int] = None


class StockDetail(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    code:           str
    name:           str
    market:         str
    industry:       Optional[str] = None
    latest_close:   Optional[Decimal] = None
    avg_vol_20d:    Optional[Decimal] = None
    conc_ratio:     Optional[Decimal] = None
    inst_flow_30d:  list[InstFlowPoint] = []


# ── Watchlist ─────────────────────────────────────────────────
class WatchlistAdd(BaseModel):
    stock_code: str = Field(..., min_length=4, max_length=6)


class WatchlistItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    stock_code: str
    name:       Optional[str] = None
    added_at:   datetime


# Forward ref
TokenResponse.model_rebuild()
