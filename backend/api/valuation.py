"""
StockRadar - 股價淨值比評級

規則（見 docs/roadmap/07-pb-valuation.md）：
  在同產業（上市＋上櫃）裡依 PB 由低到高排名
    排在最低的 25%  → 便宜
    排在最高的 25%  → 昂貴
    其餘            → 普通
  PB 空白（淨值為負或沒有資料）或同產業不到 10 檔 → 不評級

不寫死任何產業的 PB 門檻：各產業的 PB 每年都在變，每次查詢都用當天資料重新排名。
"""
from datetime import date, timedelta
from typing import Optional

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.selectable import CTE

from models.database import Stock, Valuation

CHEAP_PCT        = 0.25   # 產業排名百分位 ≤ 此值 → 便宜
EXPENSIVE_PCT    = 0.75   # 產業排名百分位 ≥ 此值 → 昂貴
MIN_INDUSTRY_N   = 10     # 同產業有效檔數少於此值不評級（參考文章：不到 10 家的產業不單獨列）
STALE_AFTER_DAYS = 10     # 估值資料超過這麼多天沒更新就不採用（例如已下市）

RATING_CHEAP     = "cheap"
RATING_FAIR      = "fair"
RATING_EXPENSIVE = "expensive"


def rate_pb(pb, industry_pct, industry_n) -> Optional[str]:
    """回傳 cheap / fair / expensive；不符合評級條件時回傳 None"""
    if pb is None or industry_pct is None or industry_n is None:
        return None
    if industry_n < MIN_INDUSTRY_N:
        return None
    if industry_pct <= CHEAP_PCT:
        return RATING_CHEAP
    if industry_pct >= EXPENSIVE_PCT:
        return RATING_EXPENSIVE
    return RATING_FAIR


async def ranked_valuations(db: AsyncSession) -> Optional[CTE]:
    """
    每檔最新一筆估值，附上同產業的排名百分位、中位數、最低、最高、檔數。
    還沒有任何估值資料時回傳 None。

    欄位：stock_code, valuation_date, pe_ratio, pb_ratio, dividend_yield, bvps,
          fin_period, industry, industry_pb_pct, industry_pb_median,
          industry_pb_min, industry_pb_max, industry_n

    成本：先用 trade_date 索引取最新日期（O(log n)），只掃最近 STALE_AFTER_DAYS 天
    （約 2,000 檔 × 數個交易日），排名與分組由資料庫一次排序完成，O(N log N)。
    """
    latest_day: Optional[date] = await db.scalar(select(func.max(Valuation.trade_date)))
    if latest_day is None:
        return None
    cutoff = latest_day - timedelta(days=STALE_AFTER_DAYS)

    # 兩市發布時間可能不同，所以每檔各自取自己的最新日期，不用全市場同一天
    latest = (
        select(Valuation.stock_code, func.max(Valuation.trade_date).label("d"))
        .where(Valuation.trade_date >= cutoff)
        .group_by(Valuation.stock_code)
        .subquery()
    )
    base = (
        select(
            Valuation.stock_code,
            Valuation.trade_date.label("valuation_date"),
            Valuation.pe_ratio,
            Valuation.pb_ratio,
            Valuation.dividend_yield,
            Valuation.bvps,
            Valuation.fin_period,
            Stock.industry,
        )
        .join(latest, and_(
            latest.c.stock_code == Valuation.stock_code,
            latest.c.d == Valuation.trade_date,
        ))
        .join(Stock, Stock.code == Valuation.stock_code)
        .subquery()
    )
    # PERCENTILE_CONT 是有序集合聚合，不能當視窗函式用，所以中位數另外 GROUP BY
    stats = (
        select(
            base.c.industry,
            func.percentile_cont(0.5).within_group(base.c.pb_ratio).label("industry_pb_median"),
            func.min(base.c.pb_ratio).label("industry_pb_min"),
            func.max(base.c.pb_ratio).label("industry_pb_max"),
            func.count().label("industry_n"),
        )
        .where(base.c.pb_ratio.isnot(None))
        .group_by(base.c.industry)
        .subquery()
    )
    return (
        select(
            base,
            # PB 空白的股票自成一組排名，不會擠掉有 PB 的股票的名次
            func.percent_rank().over(
                partition_by=[base.c.industry, base.c.pb_ratio.is_(None)],
                order_by=base.c.pb_ratio,
            ).label("industry_pb_pct"),
            stats.c.industry_pb_median,
            stats.c.industry_pb_min,
            stats.c.industry_pb_max,
            stats.c.industry_n,
        )
        .outerjoin(stats, stats.c.industry == base.c.industry)
        # 先把全市場排名算好一次再拿去 JOIN。不加 MATERIALIZED 的話，PostgreSQL
        # 會把這段併進外層的大查詢一起規劃，實測篩選 API 從 27 ms 變成 355 ms。
        .cte("ranked_valuations")
        .prefix_with("MATERIALIZED")
    )


def valuation_fields(row) -> dict:
    """把 ranked_valuations 的一列轉成 API 欄位；row 為 None 時全部空白"""
    if row is None or getattr(row, "valuation_date", None) is None:
        return {}
    has_pb = row.pb_ratio is not None
    pct = row.industry_pb_pct if has_pb else None
    n = row.industry_n if has_pb else None
    return {
        "valuation_date":     row.valuation_date,
        "pe_ratio":           row.pe_ratio,
        "pb_ratio":           row.pb_ratio,
        "dividend_yield":     row.dividend_yield,
        "bvps":               row.bvps,
        "fin_period":         row.fin_period,
        "pb_rating":          rate_pb(row.pb_ratio, pct, n),
        "industry_pb_pct":    round(pct, 4) if pct is not None else None,
        "industry_pb_median": round(row.industry_pb_median, 2) if row.industry_pb_median is not None else None,
        "industry_n":         n,
    }


async def valuation_map(db: AsyncSession, codes: list[str]) -> dict[str, dict]:
    """
    指定股票的估值欄位，{代號: 欄位}。排名仍以全市場同產業計算，只是回傳時篩出這些代號。

    篩選 API 用這個另外查一次，再用代號合併（O(n)），不把排名子查詢 JOIN 進篩選的大查詢：
    實測 JOIN 進去會讓 PostgreSQL 選到較差的執行計畫（27 ms → 140 ms），分開查合計約 50 ms。
    """
    ranked = await ranked_valuations(db)
    if ranked is None or not codes:
        return {}
    rows = (await db.execute(select(ranked).where(ranked.c.stock_code.in_(codes)))).all()
    return {r.stock_code: valuation_fields(r) for r in rows}
