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
    role: str = "user"
    status: str = "active"


class RegisterResponse(BaseModel):
    """
    註冊成功不再直接回 token —— 帳號要等管理員核准才能用。
    刻意跟 TokenResponse 分成兩個型別，讓「註冊完就登入」這件事
    在型別層面就不可能發生，而不是靠開發者記得不要回 token。
    """
    status: str = "pending_approval"
    message: str = "已送出申請，管理員核准後你會收到通知信"


# ── Admin ─────────────────────────────────────────────────────
class AdminUserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    email: EmailStr
    name: Optional[str] = None
    role: str
    status: str
    created_at: Optional[datetime] = None
    approved_at: Optional[datetime] = None
    last_login_at: Optional[datetime] = None


# ── Screen ────────────────────────────────────────────────────
class ScreenFilter(BaseModel):
    """篩選參數"""
    min_avg_vol: int    = Field(2000, ge=0,    description="日均量門檻（張）")
    min_conc:    float  = Field(40.0, ge=0,    le=100, description="集中度門檻 %")
    industries:  Optional[list[str]] = None    # 產業類別過濾
    markets:     Optional[list[str]] = None    # ["TWSE", "TPEX"]
    only_inst_buy: bool = False                # 只顯示三大法人買超


class ValuationFields(BaseModel):
    """
    股價淨值比相關欄位（篩選結果、個股、同產業比較共用）。
    pb_rating：cheap 便宜 / fair 普通 / expensive 昂貴 / None 不評級
    """
    valuation_date:     Optional[date] = None       # 估值資料日期
    pe_ratio:           Optional[Decimal] = None    # 本益比；None 代表虧損或無資料
    pb_ratio:           Optional[Decimal] = None    # 股價淨值比
    dividend_yield:     Optional[Decimal] = None    # 殖利率 %
    bvps:               Optional[Decimal] = None    # 每股淨值（收盤價 ÷ PB）
    fin_period:         Optional[str] = None        # 財報季別，例如 115/Q3
    pb_rating:          Optional[str] = None
    industry_pb_pct:    Optional[float] = None      # 同產業 PB 排名百分位（0 最低、1 最高）
    industry_pb_median: Optional[float] = None      # 同產業 PB 中位數
    industry_n:         Optional[int] = None        # 同產業有 PB 的檔數
    # 跟自己的歷史比（過去 5 年每月一筆，不含本月）
    history_rating:     Optional[str] = None        # cheap / fair / expensive / None
    history_pb_pct:     Optional[float] = None      # 目前 PB 在自己歷史中的位置（0 最低、1 最高）
    history_n:          Optional[int] = None        # 歷史有幾個月
    history_since:      Optional[date] = None       # 歷史從哪一天開始
    history_pb_p25:     Optional[float] = None
    history_pb_p50:     Optional[float] = None
    history_pb_p75:     Optional[float] = None
    # 參考價位 = 每股淨值 × 歷史 PB 第 25／50／75 百分位
    price_cheap:        Optional[float] = None
    price_fair:         Optional[float] = None
    price_expensive:    Optional[float] = None


class ScreenItem(ValuationFields):
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


class StockDetail(ValuationFields):
    model_config = ConfigDict(from_attributes=True)
    code:           str
    name:           str
    market:         str
    industry:       Optional[str] = None
    latest_close:   Optional[Decimal] = None
    avg_vol_20d:    Optional[Decimal] = None
    conc_ratio:     Optional[Decimal] = None
    inst_flow_30d:  list[InstFlowPoint] = []


# ── Valuation ─────────────────────────────────────────────────
class IndustryValuationItem(ValuationFields):
    code:       str
    name:       str
    short_name: Optional[str] = None
    market:     str
    close:      Optional[Decimal] = None   # 估值資料當天的收盤價


class IndustryValuation(BaseModel):
    industry:  str
    n:         int = 0                      # 有 PB 的檔數
    median:    Optional[float] = None
    min:       Optional[float] = None
    max:       Optional[float] = None
    items:     list[IndustryValuationItem]  # 依 PB 由低到高，沒有 PB 的排最後


class PbPoint(BaseModel):
    date: date
    pb:   float


class PbHistory(BaseModel):
    code:   str
    points: list[PbPoint]                  # 每月一點，最後一點是最新一天
    p25:    Optional[float] = None
    p50:    Optional[float] = None
    p75:    Optional[float] = None
    n:      int = 0                        # 用來算百分位的月數（不含本月）


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
