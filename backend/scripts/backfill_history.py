"""
StockRadar - 歷史均量回補腳本（v3：yfinance）

用途：
  首次部署或 DB 資料有誤時，補入近 2 個月的每日行情，
  使 compute_avg_vol_from_db() 能算出準確的 20 日均量。

策略：
  - 使用 yfinance（支援台股 .TW / .TWO 後綴）
  - 每批 100 支同時下載，約 10-15 次 API 呼叫完成全部
  - 完全繞開 TWSE 網站防爬，穩定性高

執行方式（在宿主機 Python 直連 Docker postgres）：
  DATABASE_URL=postgresql+asyncpg://stockradar:stockradar_dev_pw@localhost:5432/stockradar \
  python scripts/backfill_history.py

或在 Docker container 內（需先 pip install yfinance）：
  pip install yfinance && python scripts/backfill_history.py

環境變數：
  BACKFILL_PERIOD=2mo   # yfinance period（預設 2mo，支援 1mo/3mo）
  BATCH_SIZE=100         # 每批股票數（預設 100）

【變更履歷】
  2026-05-09  v1  STOCK_DAY_ALL（錯誤：忽略日期）
  2026-05-09  v2  STOCK_DAY 個股月歷史（TWSE 擋 Docker IP）
  2026-05-09  v3  改用 yfinance（穩定，支援本機 + Docker）
"""
import asyncio
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import yfinance as yf
import pandas as pd
from sqlalchemy import text

from models.database import AsyncSessionLocal

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("backfill")

# ── 設定 ──────────────────────────────────────────────────────
PERIOD     = os.getenv("BACKFILL_PERIOD", "2mo")   # yfinance period
BATCH_SIZE = int(os.getenv("BATCH_SIZE", "100"))    # 每批股票數
DB_BATCH   = 500                                     # 每次 upsert 筆數


# ── 取得所有需要回補的股票代號 ────────────────────────────────
async def get_codes_by_market() -> tuple[list[str], list[str]]:
    """
    從 daily_quotes 取最近一天出現的代號，
    回傳 (twse_codes, tpex_codes)
    TWSE = 4 碼純數字，TPEX = 5 碼純數字（含 0 開頭 ETF）
    """
    async with AsyncSessionLocal() as session:
        result = await session.execute(text("""
            SELECT DISTINCT dq.stock_code, s.market
            FROM daily_quotes dq
            LEFT JOIN stocks s ON s.code = dq.stock_code
            WHERE dq.trade_date = (SELECT MAX(trade_date) FROM daily_quotes)
              AND dq.stock_code ~ '^[0-9]{4,5}$'
            ORDER BY dq.stock_code
        """))
        rows = result.fetchall()

    twse, tpex = [], []
    for code, market in rows:
        if market == "TPEX":
            tpex.append(code)
        else:
            twse.append(code)   # 含 market IS NULL 的也當 TWSE 處理

    logger.info(f"股票代號：TWSE {len(twse)} 支，TPEX {len(tpex)} 支")
    return twse, tpex


# ── yfinance 批量下載 ─────────────────────────────────────────
def download_batch(codes: list[str], suffix: str) -> pd.DataFrame:
    """
    下載一批股票的歷史資料。
    回傳 DataFrame，index=Date，columns=MultiIndex(OHLCV, ticker)
    """
    tickers = [f"{c}{suffix}" for c in codes]
    df = yf.download(
        tickers,
        period=PERIOD,
        interval="1d",
        auto_adjust=True,   # 自動還原權息
        progress=False,
        group_by="ticker",  # MultiIndex：(ticker, field)
    )
    return df


# ── 從 yfinance DataFrame 提取 records ───────────────────────
def extract_records(df: pd.DataFrame, codes: list[str], suffix: str) -> list[dict]:
    """
    將 yfinance MultiIndex DataFrame 轉為 daily_quotes upsert 用的 list[dict]
    """
    records = []

    # 單支股票時 yfinance 不產生 MultiIndex，做相容處理
    if len(codes) == 1:
        ticker = f"{codes[0]}{suffix}"
        sub = df[["Open", "High", "Low", "Close", "Volume"]].copy()
        sub.columns = ["open", "high", "low", "close", "volume"]
        sub["stock_code"] = codes[0]
        sub.index.name = "trade_date"
        sub = sub.reset_index()
        sub["volume"] = (sub["volume"] / 1000).round(0).astype("Int64")
        for _, row in sub.dropna(subset=["close"]).iterrows():
            if row["volume"] is None or row["volume"] <= 0:
                continue
            records.append({
                "stock_code": row["stock_code"],
                "trade_date": row["trade_date"].date() if hasattr(row["trade_date"], "date") else row["trade_date"],
                "open":       float(row["open"]) if pd.notna(row["open"]) else None,
                "high":       float(row["high"]) if pd.notna(row["high"]) else None,
                "low":        float(row["low"])  if pd.notna(row["low"])  else None,
                "close":      float(row["close"]),
                "volume":     int(row["volume"]),
            })
        return records

    # 多支股票：MultiIndex columns
    for code in codes:
        ticker = f"{code}{suffix}"
        if ticker not in df.columns.get_level_values(0):
            continue
        try:
            sub = df[ticker][["Open", "High", "Low", "Close", "Volume"]].copy()
            sub.columns = ["open", "high", "low", "close", "volume"]
            sub = sub.dropna(subset=["close"])
            sub["volume"] = (sub["volume"] / 1000).round(0)
        except (KeyError, TypeError):
            continue

        for dt, row in sub.iterrows():
            vol = row["volume"]
            if pd.isna(vol) or vol <= 0:
                continue
            trade_date = dt.date() if hasattr(dt, "date") else dt
            records.append({
                "stock_code": code,
                "trade_date": trade_date,
                "open":       float(row["open"]) if pd.notna(row["open"]) else None,
                "high":       float(row["high"]) if pd.notna(row["high"]) else None,
                "low":        float(row["low"])  if pd.notna(row["low"])  else None,
                "close":      float(row["close"]),
                "volume":     int(vol),
            })

    return records


# ── Upsert 進 daily_quotes ────────────────────────────────────
async def upsert_records(records: list[dict]) -> int:
    if not records:
        return 0
    async with AsyncSessionLocal() as session:
        for i in range(0, len(records), DB_BATCH):
            batch = records[i : i + DB_BATCH]
            await session.execute(
                text("""
                    INSERT INTO daily_quotes
                        (stock_code, trade_date, open, high, low, close, volume, created_at)
                    VALUES
                        (:stock_code, :trade_date, :open, :high, :low, :close, :volume, NOW())
                    ON CONFLICT (stock_code, trade_date)
                    DO UPDATE SET
                        open   = EXCLUDED.open,
                        high   = EXCLUDED.high,
                        low    = EXCLUDED.low,
                        close  = EXCLUDED.close,
                        volume = EXCLUDED.volume
                """),
                batch,
            )
        await session.commit()
    return len(records)


# ── 驗收查詢 ─────────────────────────────────────────────────
async def verify():
    async with AsyncSessionLocal() as session:
        result = await session.execute(text("""
            SELECT trade_date, volume, close
            FROM daily_quotes
            WHERE stock_code = '2330'
            ORDER BY trade_date DESC LIMIT 6
        """))
        rows = result.fetchall()
    logger.info("驗收 2330（台積電）近 6 日：")
    for r in rows:
        logger.info(f"  {r.trade_date}  量={r.volume:,}張  收={r.close}")


# ── 主流程 ────────────────────────────────────────────────────
async def run_backfill():
    logger.info("=" * 60)
    logger.info(f"StockRadar 歷史均量回補 v3（yfinance，period={PERIOD}）")
    logger.info("=" * 60)

    twse_codes, tpex_codes = await get_codes_by_market()

    total_written = 0

    for suffix, codes, label in [(".TW", twse_codes, "TWSE"), (".TWO", tpex_codes, "TPEX")]:
        if not codes:
            continue
        logger.info(f"▶ {label}：{len(codes)} 支，每批 {BATCH_SIZE}")
        done = 0
        for start in range(0, len(codes), BATCH_SIZE):
            batch_codes = codes[start : start + BATCH_SIZE]
            try:
                df = download_batch(batch_codes, suffix)
                records = extract_records(df, batch_codes, suffix)
                written = await upsert_records(records)
                total_written += written
            except Exception as e:
                logger.warning(f"  批次 {start}-{start+len(batch_codes)} 失敗：{e}")
                written = 0

            done += len(batch_codes)
            logger.info(
                f"  {label} 進度 {done}/{len(codes)}，"
                f"本批 {written} 筆，累計 {total_written:,} 筆"
            )

    logger.info("-" * 60)
    await verify()
    logger.info("=" * 60)
    logger.info(f"✅ 回補完成，共寫入 {total_written:,} 筆")
    logger.info("=" * 60)


if __name__ == "__main__":
    asyncio.run(run_backfill())
