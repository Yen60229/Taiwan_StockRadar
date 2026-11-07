"""
StockRadar - Valuation Routes
GET /api/valuation/industry?industry=半導體業   同產業所有股票的股價淨值比排名
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_current_user, get_db_session
from api.schemas import IndustryValuation, IndustryValuationItem
from api.valuation import ranked_valuations, valuation_fields
from models.database import DailyQuote, Stock, User

router = APIRouter(prefix="/api/valuation", tags=["valuation"])


@router.get("/industry", response_model=IndustryValuation)
async def industry_valuation(
    industry: str = Query(..., min_length=1, max_length=30),
    db:   AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    """
    回傳全市場（上市＋上櫃）同產業的每一檔，依 PB 由低到高排序。
    「只看篩選結果」由前端用篩選結果的代號過濾，不必再查一次資料庫。
    """
    ranked = await ranked_valuations(db)
    if ranked is None:
        return IndustryValuation(industry=industry, items=[])

    rows = (await db.execute(
        select(ranked, Stock.name, Stock.short_name, Stock.market, DailyQuote.close)
        .join(Stock, Stock.code == ranked.c.stock_code)
        # 用估值當天的收盤價，跟 PB、每股淨值是同一天的數字
        .outerjoin(DailyQuote, and_(
            DailyQuote.stock_code == ranked.c.stock_code,
            DailyQuote.trade_date == ranked.c.valuation_date,
        ))
        .where(ranked.c.industry == industry)
        .order_by(ranked.c.pb_ratio.asc().nulls_last(), ranked.c.stock_code)
    )).all()

    items = [
        IndustryValuationItem(
            code=r.stock_code, name=r.name, short_name=r.short_name,
            market=r.market, close=r.close, **valuation_fields(r),
        )
        for r in rows
    ]
    # 產業統計每列都一樣，取第一筆有 PB 的即可
    first = next((r for r in rows if r.pb_ratio is not None), None)
    return IndustryValuation(
        industry=industry,
        n=first.industry_n if first else 0,
        median=round(first.industry_pb_median, 2) if first else None,
        min=float(first.industry_pb_min) if first else None,
        max=float(first.industry_pb_max) if first else None,
        items=items,
    )
