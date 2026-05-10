"""
StockRadar - Screen Routes
GET /api/screen          篩選結果（雙條件 + 法人）
GET /api/screen/industries  取得所有產業類別清單
"""
from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import and_, distinct, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_current_user_optional, get_db_session
from api.schemas import ScreenFilter, ScreenItem, ScreenResponse
from models.database import (
    ChipConcentration,
    DailyQuote,
    InstitutionalFlow,
    OwnershipRatio,
    Stock,
    User,
    Watchlist,
)

router = APIRouter(prefix="/api/screen", tags=["screen"])


@router.get("", response_model=ScreenResponse)
async def screen_stocks(
    min_avg_vol:   int   = Query(2000, ge=0),
    min_conc:      float = Query(40.0, ge=0, le=100),
    industries:    Optional[list[str]] = Query(None),
    markets:       Optional[list[str]] = Query(None),
    only_inst_buy: bool  = Query(False),
    db:   AsyncSession = Depends(get_db_session),
    user: Optional[User] = Depends(get_current_user_optional),
):
    """
    核心篩選邏輯：
      JOIN stocks + 最新 daily_quotes + 最新 chip_concentration + 最新 institutional_flow
      WHERE avg_vol_20d >= min_avg_vol AND conc_ratio >= min_conc
      [+ 產業 / 市場 / 法人買超 過濾]
    """
    # 取最新各表日期
    latest_quote_date  = await db.scalar(select(func.max(DailyQuote.trade_date)))
    latest_chip_date   = await db.scalar(select(func.max(ChipConcentration.week_date)))
    latest_inst_date   = await db.scalar(select(func.max(InstitutionalFlow.trade_date)))
    latest_own_date    = await db.scalar(select(func.max(OwnershipRatio.report_date)))

    if not latest_quote_date or not latest_chip_date:
        return ScreenResponse(total=0, items=[], filters=ScreenFilter(
            min_avg_vol=min_avg_vol, min_conc=min_conc,
            industries=industries, markets=markets, only_inst_buy=only_inst_buy,
        ))

    # 主查詢
    q = (
        select(
            Stock.code, Stock.name, Stock.short_name, Stock.market, Stock.industry,
            DailyQuote.close, DailyQuote.volume, DailyQuote.avg_vol_20d,
            ChipConcentration.conc_ratio,
            InstitutionalFlow.foreign_net,
            InstitutionalFlow.trust_net,
            InstitutionalFlow.dealer_net,
            InstitutionalFlow.total_net,
            OwnershipRatio.foreign_hold_ratio,
            OwnershipRatio.trust_hold_ratio,
            OwnershipRatio.director_hold_ratio,
        )
        .join(DailyQuote, and_(
            DailyQuote.stock_code == Stock.code,
            DailyQuote.trade_date == latest_quote_date,
        ))
        .join(ChipConcentration, and_(
            ChipConcentration.stock_code == Stock.code,
            ChipConcentration.week_date  == latest_chip_date,
        ))
        .outerjoin(InstitutionalFlow, and_(
            InstitutionalFlow.stock_code == Stock.code,
            InstitutionalFlow.trade_date == latest_inst_date,
        ))
        .outerjoin(OwnershipRatio, and_(
            OwnershipRatio.stock_code   == Stock.code,
            OwnershipRatio.report_date  == latest_own_date,
        ))
        .where(
            DailyQuote.avg_vol_20d >= min_avg_vol,
            ChipConcentration.conc_ratio >= min_conc,
        )
    )
    if industries:
        q = q.where(Stock.industry.in_(industries))
    if markets:
        q = q.where(Stock.market.in_(markets))
    if only_inst_buy:
        q = q.where(InstitutionalFlow.total_net > 0)

    q = q.order_by(ChipConcentration.conc_ratio.desc())
    rows = (await db.execute(q)).all()

    # 取得使用者自選清單
    watchlist_codes: set[str] = set()
    if user:
        wl = await db.execute(select(Watchlist.stock_code).where(Watchlist.user_id == user.id))
        watchlist_codes = {r[0] for r in wl}

    items = [
        ScreenItem(
            code=r.code, name=r.name, short_name=r.short_name, market=r.market, industry=r.industry,
            close=r.close, volume=r.volume, avg_vol_20d=r.avg_vol_20d,
            conc_ratio=r.conc_ratio,
            foreign_net=r.foreign_net, trust_net=r.trust_net,
            dealer_net=r.dealer_net, total_net=r.total_net,
            foreign_hold_ratio=r.foreign_hold_ratio,
            trust_hold_ratio=r.trust_hold_ratio,
            director_hold_ratio=r.director_hold_ratio,
            in_watchlist=(r.code in watchlist_codes),
        )
        for r in rows
    ]

    return ScreenResponse(
        total=len(items),
        items=items,
        filters=ScreenFilter(
            min_avg_vol=min_avg_vol, min_conc=min_conc,
            industries=industries, markets=markets, only_inst_buy=only_inst_buy,
        ),
        last_update=latest_quote_date,
    )


@router.get("/industries", response_model=list[str])
async def list_industries(db: AsyncSession = Depends(get_db_session)):
    rows = await db.execute(
        select(distinct(Stock.industry))
        .where(Stock.industry.isnot(None))
        .order_by(Stock.industry)
    )
    return [r[0] for r in rows]
