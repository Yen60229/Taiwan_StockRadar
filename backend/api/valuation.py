"""
StockRadar - 股價淨值比評級

規則（見 docs/roadmap/07-pb-valuation.md）：
  在同產業（上市＋上櫃）裡依 PB 由低到高排名
    排在最低的 25%  → 便宜
    排在最高的 25%  → 昂貴
    其餘            → 普通
  PB 空白（淨值為負或沒有資料）或同產業不到 10 檔 → 不評級

不寫死任何產業的 PB 門檻：各產業的 PB 每年都在變，每次查詢都用當天資料重新排名。

第二階段：跟自己的歷史比
  取這檔過去 5 年每個月最新一筆 PB（valuation_monthly，不含本月），看目前 PB 落在哪個位置
    排在最低的 25%  → 便宜
    排在最高的 25%  → 昂貴
  歷史不到 36 個月（3 年）不評級
  參考價位 = 每股淨值 × 自己歷史 PB 的第 25／50／75 百分位
"""
from datetime import date, timedelta
from typing import Optional

from sqlalchemy import and_, bindparam, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.selectable import CTE

from models.database import Stock, Valuation

CHEAP_PCT        = 0.25   # 產業排名百分位 ≤ 此值 → 便宜
EXPENSIVE_PCT    = 0.75   # 產業排名百分位 ≥ 此值 → 昂貴
MIN_INDUSTRY_N   = 10     # 同產業有效檔數少於此值不評級（參考文章：不到 10 家的產業不單獨列）
STALE_AFTER_DAYS = 10     # 估值資料超過這麼多天沒更新就不採用（例如已下市）
HIST_YEARS       = 5      # 跟自己比：往回看幾年
MIN_HIST_MONTHS  = 36     # 跟自己比：歷史少於這麼多個月不評級

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


def rate_history(history_pct, history_n) -> Optional[str]:
    """跟自己歷史比的評級；歷史不足 MIN_HIST_MONTHS 個月回傳 None"""
    if history_pct is None or history_n is None or history_n < MIN_HIST_MONTHS:
        return None
    if history_pct <= CHEAP_PCT:
        return RATING_CHEAP
    if history_pct >= EXPENSIVE_PCT:
        return RATING_EXPENSIVE
    return RATING_FAIR


async def latest_valuation_day(db: AsyncSession) -> Optional[date]:
    """估值資料的最新日期（走 trade_date 索引，O(log n)）"""
    return await db.scalar(select(func.max(Valuation.trade_date)))


async def ranked_valuations(db: AsyncSession, latest_day: Optional[date] = None) -> Optional[CTE]:
    """
    每檔最新一筆估值，附上同產業的排名百分位、中位數、最低、最高、檔數。
    還沒有任何估值資料時回傳 None。

    欄位：stock_code, valuation_date, pe_ratio, pb_ratio, dividend_yield, bvps,
          fin_period, industry, industry_pb_pct, industry_pb_median,
          industry_pb_min, industry_pb_max, industry_n

    成本：先用 trade_date 索引取最新日期（O(log n)），只掃最近 STALE_AFTER_DAYS 天
    （約 2,000 檔 × 數個交易日），排名與分組由資料庫一次排序完成，O(N log N)。
    """
    latest_day = latest_day or await latest_valuation_day(db)
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
    if not codes:
        return {}
    latest_day = await latest_valuation_day(db)
    ranked = await ranked_valuations(db, latest_day)
    if ranked is None:
        return {}
    rows = (await db.execute(select(ranked).where(ranked.c.stock_code.in_(codes)))).all()
    out = {r.stock_code: valuation_fields(r) for r in rows}
    return merge_history(out, await history_map(db, codes, latest_day))


# ── 跟自己的歷史比 ────────────────────────────────────────────
def history_window(latest_day: date) -> tuple[date, date]:
    """(起日, 迄日)：過去 HIST_YEARS 年，到本月一日為止（本月不算歷史）"""
    month_start = latest_day.replace(day=1)
    return month_start.replace(year=month_start.year - HIST_YEARS), month_start


# 每月快照表：每檔每月一筆（該月最新一天的 PB），見 models.database.ValuationMonthly。
# 每檔最多讀 60 筆，總量固定是「檔數 × 月數」，不會隨每日資料累積而變慢。
_MONTHLY_SQL = """
    SELECT stock_code, trade_date, pb_ratio
    FROM valuation_monthly
    WHERE stock_code IN :codes
      AND month >= :since AND month < :until
"""

_HISTORY_STATS_SQL = text(f"""
    WITH cur AS (
        SELECT DISTINCT ON (stock_code) stock_code, pb_ratio
        FROM valuations
        WHERE stock_code IN :codes AND trade_date >= :stale_cutoff
        ORDER BY stock_code, trade_date DESC
    ), monthly AS ({_MONTHLY_SQL})
    SELECT m.stock_code,
           COUNT(*)                                                 AS n,
           MIN(m.trade_date)                                        AS since,
           PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY m.pb_ratio) AS p25,
           PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY m.pb_ratio) AS p50,
           PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY m.pb_ratio) AS p75,
           COUNT(*) FILTER (WHERE m.pb_ratio < c.pb_ratio)          AS below,
           COUNT(*) FILTER (WHERE m.pb_ratio = c.pb_ratio)          AS equal,
           MAX(c.pb_ratio)                                          AS current_pb
    FROM monthly m
    LEFT JOIN cur c USING (stock_code)
    GROUP BY m.stock_code
""").bindparams(bindparam("codes", expanding=True))


async def history_map(
    db: AsyncSession, codes: list[str], latest_day: Optional[date] = None,
) -> dict[str, dict]:
    """
    {代號: 跟自己歷史比的欄位}。沒有歷史的股票不會出現在結果裡。

    成本：每檔最多 60 筆月快照（走 (stock_code, month) 唯一索引）+ 最近幾天的估值；
    百分位與「目前排在哪」在同一次 GROUP BY 算完，不把樣本傳回 Python。
    """
    if not codes:
        return {}
    latest_day = latest_day or await latest_valuation_day(db)
    if latest_day is None:
        return {}
    since, until = history_window(latest_day)
    rows = (await db.execute(_HISTORY_STATS_SQL, {
        "codes": list(codes), "since": since, "until": until,
        "stale_cutoff": latest_day - timedelta(days=STALE_AFTER_DAYS),
    })).all()

    out = {}
    for r in rows:
        # 中位排名：比目前低的算 1、相等的算一半，避免歷史 PB 長期持平時被判成極端
        pct = (r.below + 0.5 * r.equal) / r.n if r.current_pb is not None else None
        out[r.stock_code] = {
            "history_pb_pct":  round(pct, 4) if pct is not None else None,
            "history_rating":  rate_history(pct, r.n),
            "history_n":       r.n,
            "history_since":   r.since,
            "history_pb_p25":  round(r.p25, 2),
            "history_pb_p50":  round(r.p50, 2),
            "history_pb_p75":  round(r.p75, 2),
        }
    return out


def merge_history(fields: dict[str, dict], history: dict[str, dict]) -> dict[str, dict]:
    """
    把歷史欄位併進估值欄位，並算出參考價位（每股淨值 × 歷史 PB 百分位）。
    沒有每股淨值（例如淨值為負），或歷史不到 MIN_HIST_MONTHS 個月，就不給參考價位：
    跟評級同一個門檻，幾個月的資料算出來的「便宜價」沒有參考價值，顯示出來反而誤導。
    """
    for code, h in history.items():
        f = fields.setdefault(code, {})
        f.update(h)
        bvps = f.get("bvps")
        if bvps is not None and h["history_n"] >= MIN_HIST_MONTHS:
            b = float(bvps)
            f["price_cheap"]     = round(b * h["history_pb_p25"], 2)
            f["price_fair"]      = round(b * h["history_pb_p50"], 2)
            f["price_expensive"] = round(b * h["history_pb_p75"], 2)
    return fields


async def history_series(db: AsyncSession, code: str) -> list[tuple[date, float]]:
    """個股頁的 PB 走勢：過去 HIST_YEARS 年每月一點，最後一點是最新一天"""
    latest_day = await latest_valuation_day(db)
    if latest_day is None:
        return []
    since, _ = history_window(latest_day)
    rows = (await db.execute(
        text(_MONTHLY_SQL + " ORDER BY month").bindparams(bindparam("codes", expanding=True)),
        {"codes": [code], "since": since, "until": latest_day + timedelta(days=1)},
    )).all()
    return [(r.trade_date, float(r.pb_ratio)) for r in rows]
