"""
StockRadar — 三大法人買賣超歷史回補

用途：
  個股頁的「近 30 日三大法人」折線圖需要歷史序列，但每日 pipeline 只抓當天，
  初次部署後 institutional_flow 只會有一天的資料。這支腳本補回過去 N 天。

資料來源（皆支援指定日期）：
  TWSE：https://www.twse.com.tw/rwd/zh/fund/T86?date=YYYYMMDD
  TPEX：https://www.tpex.org.tw/www/zh-tw/insti/dailyTrade?date=115/09/04

執行：
  docker compose -f docker-compose.prod.yml exec scheduler \
      python scripts/backfill_inst_flow.py [天數]

  天數 = 往回追溯的「日曆天」，預設 45（約 30 個交易日）。

行為：
  ・週六 / 週日直接跳過，不發請求
  ・國定假日由 API 回空值自動略過（不會寫入、不會 raise）
  ・每天之間 sleep，避免對來源造成壓力
  ・upsert 冪等，重複執行安全
"""
import asyncio
import logging
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx

from models.database import AsyncSessionLocal
from pipeline.data_pipeline import upsert_institutional_flow
from scraper.twse_scraper import (
    HEADERS as TWSE_HEADERS,
    fetch_institutional_flow_on as twse_inst_on,
)
from scraper.tpex_scraper import (
    HEADERS as TPEX_HEADERS,
    fetch_institutional_flow_on as tpex_inst_on,
)

logging.basicConfig(
    level=logging.WARNING,          # 只顯示本腳本的 INFO，壓掉 httpx 逐筆請求 log
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("backfill_inst")
logger.setLevel(logging.INFO)

DAYS_BACK  = int(sys.argv[1]) if len(sys.argv) > 1 else 45
REQ_DELAY  = 0.8    # 每個交易日之間的間隔（秒）


async def run() -> None:
    today = date.today()
    targets = [today - timedelta(days=i) for i in range(DAYS_BACK + 1)]
    # 只留平日；國定假日交給 API 回空值處理
    targets = [d for d in targets if d.weekday() < 5]
    targets.sort()

    logger.info("=" * 60)
    logger.info(f"三大法人歷史回補：{targets[0]} ~ {targets[-1]}（{len(targets)} 個平日）")
    logger.info("=" * 60)

    total_rows = trading_days = holidays = 0

    async with httpx.AsyncClient(headers=TWSE_HEADERS, follow_redirects=True) as tc, \
               httpx.AsyncClient(headers=TPEX_HEADERS, follow_redirects=True) as pc:

        for d in targets:
            tw, tp = await asyncio.gather(twse_inst_on(tc, d), tpex_inst_on(pc, d))

            if tw.empty and tp.empty:
                holidays += 1
                logger.info(f"  {d}  —  無資料（假日或尚未公布）")
                await asyncio.sleep(REQ_DELAY)
                continue

            written = 0
            async with AsyncSessionLocal() as session:
                for df in (tw, tp):
                    if not df.empty:
                        written += await upsert_institutional_flow(session, df)

            trading_days += 1
            total_rows += written
            logger.info(f"  {d}  ✔  TWSE {len(tw):>4} / TPEX {len(tp):>4}  → 寫入 {written} 筆")
            await asyncio.sleep(REQ_DELAY)

    logger.info("-" * 60)
    logger.info(f"✅ 完成：{trading_days} 個交易日、{holidays} 個非交易日、共寫入 {total_rows:,} 筆")

    # 驗收：看看實際覆蓋了幾天
    from sqlalchemy import text
    async with AsyncSessionLocal() as session:
        row = (await session.execute(text("""
            SELECT COUNT(DISTINCT trade_date) AS days,
                   MIN(trade_date) AS first_day,
                   MAX(trade_date) AS last_day,
                   COUNT(*) AS rows
            FROM institutional_flow
        """))).one()
    logger.info(f"   institutional_flow 現有 {row.days} 個交易日"
                f"（{row.first_day} ~ {row.last_day}），共 {row.rows:,} 筆")
    logger.info("=" * 60)


if __name__ == "__main__":
    asyncio.run(run())
