"""
StockRadar - Screen Routes
GET /api/screen          篩選結果（雙條件 + 法人）
GET /api/screen/industries  取得所有產業類別清單
"""
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import and_, distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select

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


def _latest_per_stock(model, date_col) -> Select:
    """
    每檔股票各自的最新日期（而不是全市場共用一個日期）。

    背景：TWSE 與 TPEX 的行情發布時間會有落差（例如 TWSE 尚未更新仍是
    前一交易日，TPEX 已經是最新一天），此時 daily_quotes 同一天會出現
    兩個不同的 trade_date。若用「全市場 MAX(trade_date)」去 JOIN，
    日期較舊那個市場的股票會被整批排除 —— 這正是 2026-09-08 那次
    「上市全部消失」的根因。改成每檔股票各自比對自己的最新日期，
    就不會受另一個市場的發布進度影響。
    """
    return (
        select(model.stock_code.label("stock_code"), func.max(date_col).label("d"))
        .group_by(model.stock_code)
        .subquery()
    )


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
      JOIN stocks + 各股最新 daily_quotes + 各股最新 chip_concentration
                  + 各股最新 institutional_flow / ownership_ratio
      WHERE avg_vol_20d >= min_avg_vol AND conc_ratio >= min_conc
      [+ 產業 / 市場 / 法人買超 過濾]

    每張表各自取「每檔股票自己的最新日期」而非全市場共用一個日期
    （見 _latest_per_stock 的說明），避免市場間發布時間落差造成整批股票消失。
    """
    # 快速判斷 DB 是否有資料可篩（全市場層級即可，只用來決定要不要早退）
    has_quotes = await db.scalar(select(func.max(DailyQuote.trade_date)))
    has_chip   = await db.scalar(select(func.max(ChipConcentration.week_date)))

    if not has_quotes or not has_chip:
        return ScreenResponse(total=0, items=[], filters=ScreenFilter(
            min_avg_vol=min_avg_vol, min_conc=min_conc,
            industries=industries, markets=markets, only_inst_buy=only_inst_buy,
        ))

    quote_latest = _latest_per_stock(DailyQuote, DailyQuote.trade_date)
    chip_latest  = _latest_per_stock(ChipConcentration, ChipConcentration.week_date)
    inst_latest  = _latest_per_stock(InstitutionalFlow, InstitutionalFlow.trade_date)
    own_latest   = _latest_per_stock(OwnershipRatio, OwnershipRatio.report_date)

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
        .join(quote_latest, quote_latest.c.stock_code == Stock.code)
        .join(DailyQuote, and_(
            DailyQuote.stock_code == quote_latest.c.stock_code,
            DailyQuote.trade_date == quote_latest.c.d,
        ))
        .join(chip_latest, chip_latest.c.stock_code == Stock.code)
        .join(ChipConcentration, and_(
            ChipConcentration.stock_code == chip_latest.c.stock_code,
            ChipConcentration.week_date  == chip_latest.c.d,
        ))
        .outerjoin(inst_latest, inst_latest.c.stock_code == Stock.code)
        .outerjoin(InstitutionalFlow, and_(
            InstitutionalFlow.stock_code == inst_latest.c.stock_code,
            InstitutionalFlow.trade_date == inst_latest.c.d,
        ))
        .outerjoin(own_latest, own_latest.c.stock_code == Stock.code)
        .outerjoin(OwnershipRatio, and_(
            OwnershipRatio.stock_code   == own_latest.c.stock_code,
            OwnershipRatio.report_date  == own_latest.c.d,
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
        # 全市場最新日期，僅供畫面顯示「更新於」，不再用於篩選邏輯
        last_update=has_quotes,
    )


@router.get("/industries", response_model=list[str])
async def list_industries(db: AsyncSession = Depends(get_db_session)):
    rows = await db.execute(
        select(distinct(Stock.industry))
        .where(Stock.industry.isnot(None))
        .order_by(Stock.industry)
    )
    return [r[0] for r in rows]
