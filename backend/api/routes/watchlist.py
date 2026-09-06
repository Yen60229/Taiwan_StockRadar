"""
StockRadar - Watchlist Routes（需登入）
GET    /api/watchlist
POST   /api/watchlist
DELETE /api/watchlist/{code}
"""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import and_, delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_current_user, get_db_session
from api.schemas import WatchlistAdd, WatchlistItem
from models.database import Stock, User, Watchlist

router = APIRouter(prefix="/api/watchlist", tags=["watchlist"])


@router.get("", response_model=list[WatchlistItem])
async def list_watchlist(
    user: User = Depends(get_current_user),
    db:   AsyncSession = Depends(get_db_session),
):
    rows = (await db.execute(
        select(Watchlist, Stock.name)
        .outerjoin(Stock, Stock.code == Watchlist.stock_code)
        .where(Watchlist.user_id == user.id)
        .order_by(Watchlist.added_at.desc())
    )).all()

    return [
        WatchlistItem(stock_code=w.stock_code, name=name, added_at=w.added_at)
        for w, name in rows
    ]


@router.post("", response_model=WatchlistItem, status_code=201)
async def add_watchlist(
    payload: WatchlistAdd,
    user: User = Depends(get_current_user),
    db:   AsyncSession = Depends(get_db_session),
):
    # 檢查股票是否存在
    stock = (await db.execute(select(Stock).where(Stock.code == payload.stock_code))).scalar_one_or_none()

    # 直接 insert，靠 uq_watchlist(user_id, stock_code) 擋重複，避免 check-then-insert race
    item = Watchlist(user_id=user.id, stock_code=payload.stock_code)
    db.add(item)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(409, "已在自選清單")
    await db.refresh(item)

    return WatchlistItem(
        stock_code=item.stock_code,
        name=stock.name if stock else None,
        added_at=item.added_at,
    )


@router.delete("/{code}", status_code=204)
async def remove_watchlist(
    code: str,
    user: User = Depends(get_current_user),
    db:   AsyncSession = Depends(get_db_session),
):
    result = await db.execute(
        delete(Watchlist).where(and_(
            Watchlist.user_id == user.id,
            Watchlist.stock_code == code,
        ))
    )
    await db.commit()
    if result.rowcount == 0:
        raise HTTPException(404, "清單中無此股票")
