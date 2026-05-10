"""
StockRadar - Stock Detail Routes
GET /api/stocks/{code}            個股詳細
GET /api/stocks/{code}/inst-flow  近30日法人買賣超
"""
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_db_session
from api.schemas import InstFlowPoint, StockDetail
from models.database import ChipConcentration, DailyQuote, InstitutionalFlow, Stock

router = APIRouter(prefix="/api/stocks", tags=["stocks"])


@router.get("/{code}", response_model=StockDetail)
async def get_stock_detail(code: str, db: AsyncSession = Depends(get_db_session)):
    stock = (await db.execute(select(Stock).where(Stock.code == code))).scalar_one_or_none()
    if not stock:
        raise HTTPException(404, f"找不到股票 {code}")

    latest_quote = (await db.execute(
        select(DailyQuote).where(DailyQuote.stock_code == code).order_by(desc(DailyQuote.trade_date)).limit(1)
    )).scalar_one_or_none()

    latest_chip = (await db.execute(
        select(ChipConcentration).where(ChipConcentration.stock_code == code).order_by(desc(ChipConcentration.week_date)).limit(1)
    )).scalar_one_or_none()

    # 近 30 日法人
    cutoff = date.today() - timedelta(days=30)
    flow_rows = (await db.execute(
        select(InstitutionalFlow)
        .where(and_(InstitutionalFlow.stock_code == code, InstitutionalFlow.trade_date >= cutoff))
        .order_by(InstitutionalFlow.trade_date)
    )).scalars().all()

    return StockDetail(
        code=stock.code, name=stock.name, market=stock.market, industry=stock.industry,
        latest_close=latest_quote.close if latest_quote else None,
        avg_vol_20d=latest_quote.avg_vol_20d if latest_quote else None,
        conc_ratio=latest_chip.conc_ratio if latest_chip else None,
        inst_flow_30d=[
            InstFlowPoint(
                trade_date=f.trade_date, foreign_net=f.foreign_net,
                trust_net=f.trust_net, dealer_net=f.dealer_net, total_net=f.total_net,
            ) for f in flow_rows
        ],
    )
