"""
StockRadar - Valuation Routes
GET /api/valuation/industry?industry=半導體業   同產業所有股票的股價淨值比排名
GET /api/valuation/history/{code}              個股過去 5 年的 PB 走勢（每月一點）
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_current_user, get_db_session
from api.schemas import IndustryValuation, IndustryValuationItem, PbHistory, PbPoint
from api.valuation import (
    history_map, history_series, latest_valuation_day, merge_history,
    ranked_valuations, valuation_fields,
)
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
    latest_day = await latest_valuation_day(db)
    ranked = await ranked_valuations(db, latest_day)
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

    fields = merge_history(
        {r.stock_code: valuation_fields(r) for r in rows},
        await history_map(db, [r.stock_code for r in rows], latest_day),
    )
    items = [
        IndustryValuationItem(
            code=r.stock_code, name=r.name, short_name=r.short_name,
            market=r.market, close=r.close, **fields[r.stock_code],
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


@router.get("/history/{code}", response_model=PbHistory)
async def pb_history(
    code: str,
    db:   AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
):
    """過去 5 年每月一點的 PB，加上自己歷史的第 25／50／75 百分位（畫參考線用）"""
    points = await history_series(db, code)
    stats = (await history_map(db, [code])).get(code, {})
    return PbHistory(
        code=code,
        points=[PbPoint(date=d, pb=pb) for d, pb in points],
        p25=stats.get("history_pb_p25"),
        p50=stats.get("history_pb_p50"),
        p75=stats.get("history_pb_p75"),
        n=stats.get("history_n", 0),
    )
