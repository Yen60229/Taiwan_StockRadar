"""
StockRadar — 股價淨值比歷史回補（每月取一天）

用途：
  「跟自己歷史比」的評級需要每檔股票過去 5 年的 PB。每天的排程只抓當天，
  所以上線時要先跑一次這支腳本，把過去每個月最後一個交易日的估值表補進來。

  每月只取一天：5 年 = 60 天 × 2 市場 = 約 120 次請求。逐日回補要 2,400 次，
  多出 20 倍請求，對評級的準確度幫助不大。

資料來源（與每日排程同一組函式）：
  上市：www.twse.com.tw/rwd/zh/afterTrading/BWIBBU_d
  上櫃：www.tpex.org.tw/www/zh-tw/afterTrading/peQryDate

執行：
  docker compose -f docker-compose.prod.yml exec scheduler \
      python scripts/backfill_valuation.py [年數] [--force]

  年數預設 5。--force：已經有資料的月份也重抓（預設跳過）。

找交易日的方式：
  證交所遇到假日不會回「沒有資料」，而是 307 轉址到「因為安全性考量…」的頁面，
  跟被限流時一模一樣，分不出來。櫃買中心假日會清楚回 0 筆，所以先用櫃買中心
  從月底往前找到第一個有資料的平日，確定是交易日，再拿同一天去問證交所。

行為：
  ・寫入用 keep_existing（ON CONFLICT DO NOTHING），不會把每日排程算好的每股淨值蓋掉
  ・歷史列沒有當天收盤價，bvps 留空；評級只用 PB，不受影響
  ・證交所請求間隔 6 秒；被封鎖時冷卻 2、4、8 分鐘再試同一天，還是不行才跳過
  ・可以重複執行：已經回補過的月份會跳過
"""
import argparse
import asyncio
import logging
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx
from sqlalchemy import text

from models.database import AsyncSessionLocal
from pipeline.data_pipeline import upsert_valuations
from scraper.twse_scraper import HEADERS as TWSE_HEADERS
from scraper.tpex_scraper import HEADERS as TPEX_HEADERS
from scraper.valuation import fetch_tpex_on, fetch_twse_on

logging.basicConfig(
    level=logging.WARNING,          # 壓掉 httpx 逐筆請求 log，只留本腳本的進度
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("backfill_valuation")
logger.setLevel(logging.INFO)

TWSE_DELAY  = 6.0   # 秒；證交所請求太密會封鎖一段時間（回 307）
TPEX_DELAY  = 1.0   # 秒；找交易日時每問一天的間隔
# 被證交所封鎖時，同一天依序冷卻這麼久再試。實測連續約 10 次請求後被擋，
# 擋住時繼續送只會延長封鎖，所以停下來等，而不是馬上換下一個月。
TWSE_COOLDOWNS = (120, 240, 480)
# 連續這麼多個月冷卻完仍被擋，這次就不再問證交所（櫃買中心照常補），
# 否則封鎖持續時每個月要等 14 分鐘，60 個月要十幾個小時。
TWSE_GIVE_UP_AFTER = 2
MIN_ROWS    = 1500  # 某個月已有這麼多筆（兩市合計）就當作回補過了


def month_ends(today: date, years: int) -> list[date]:
    """上個月起往回 years×12 個月，每個月的最後一天（由舊到新）"""
    out = []
    first_of_month = today.replace(day=1)
    for _ in range(years * 12):
        last_day = first_of_month - timedelta(days=1)
        out.append(last_day)
        first_of_month = last_day.replace(day=1)
    return sorted(out)


def weekdays_backwards(month_end: date):
    """從月底往前列出同一個月的平日（假日交給櫃買中心判斷）"""
    d = month_end
    while d.month == month_end.month:
        if d.weekday() < 5:
            yield d
        d -= timedelta(days=1)


async def covered_months(years: int) -> set[tuple[int, int]]:
    """已經有足夠資料的月份，回補時跳過"""
    async with AsyncSessionLocal() as session:
        rows = (await session.execute(text("""
            SELECT EXTRACT(YEAR FROM trade_date)::int  AS y,
                   EXTRACT(MONTH FROM trade_date)::int AS m,
                   MAX(cnt) AS rows
            FROM (
                SELECT trade_date, COUNT(*) AS cnt
                FROM valuations
                WHERE trade_date >= :since
                GROUP BY trade_date
            ) per_day
            GROUP BY 1, 2
        """), {"since": date.today() - timedelta(days=366 * years + 31)})).all()
    return {(r.y, r.m) for r in rows if r.rows >= MIN_ROWS}


async def run(years: int, force: bool) -> None:
    targets = month_ends(date.today(), years)
    wanted = {(d.year, d.month) for d in targets}
    done = set() if force else await covered_months(years) & wanted

    logger.info("=" * 60)
    logger.info(f"股價淨值比歷史回補：{targets[0]:%Y-%m} ~ {targets[-1]:%Y-%m}（{len(targets)} 個月）")
    if done:
        logger.info(f"已有資料、跳過 {len(done)} 個月（要重抓請加 --force）")
    logger.info("=" * 60)

    written = skipped = missing = twse_missing = 0
    twse_fail_streak = 0
    async with httpx.AsyncClient(headers=TWSE_HEADERS, follow_redirects=True) as tc, \
               httpx.AsyncClient(headers=TPEX_HEADERS, follow_redirects=True) as pc:

        for month_end in targets:
            if (month_end.year, month_end.month) in done:
                skipped += 1
                continue

            # 1. 用櫃買中心找這個月最後一個交易日
            trade_day, tpex_df = None, None
            for d in weekdays_backwards(month_end):
                df = await fetch_tpex_on(pc, d)
                if not df.empty:
                    trade_day, tpex_df = d, df
                    break
                await asyncio.sleep(TPEX_DELAY)

            if trade_day is None:
                missing += 1
                logger.warning(f"  {month_end:%Y-%m}  找不到交易日，略過")
                continue

            # 2. 同一天抓證交所；被封鎖就冷卻後重試
            if twse_fail_streak >= TWSE_GIVE_UP_AFTER:
                twse_df = tpex_df.iloc[0:0]          # 這次不再問證交所
            else:
                twse_df = await fetch_twse_on(tc, trade_day)
                for wait in TWSE_COOLDOWNS:
                    if not twse_df.empty:
                        break
                    logger.warning(f"  {trade_day}  證交所沒有回資料（多半是被暫時封鎖），{wait} 秒後再試")
                    await asyncio.sleep(wait)
                    twse_df = await fetch_twse_on(tc, trade_day)
                twse_fail_streak = 0 if not twse_df.empty else twse_fail_streak + 1
                if twse_fail_streak == TWSE_GIVE_UP_AFTER:
                    logger.warning(f"  證交所連續 {TWSE_GIVE_UP_AFTER} 個月被擋，這次先只補上櫃；"
                                   "過一段時間重跑本腳本，會只補缺的月份")
            if twse_df.empty:
                twse_missing += 1

            rows = tpex_df.to_dict("records") + twse_df.to_dict("records")
            async with AsyncSessionLocal() as session:
                n = await upsert_valuations(session, rows, keep_existing=True)
            written += n
            logger.info(f"  {trade_day}  ✔  上市 {len(twse_df):>4} / 上櫃 {len(tpex_df):>4}")
            if twse_fail_streak < TWSE_GIVE_UP_AFTER:
                await asyncio.sleep(TWSE_DELAY)

    logger.info("-" * 60)
    logger.info(f"✅ 完成：送出 {written:,} 筆（已存在的不會覆蓋）、跳過 {skipped} 個月、找不到 {missing} 個月")
    if twse_missing:
        logger.warning(f"⚠️  有 {twse_missing} 個月沒抓到上市資料（被證交所擋），過一段時間再執行一次本腳本即可補上")

    # 驗收：每檔平均有幾個月的歷史
    async with AsyncSessionLocal() as session:
        row = (await session.execute(text("""
            SELECT COUNT(DISTINCT stock_code) AS stocks,
                   COUNT(DISTINCT date_trunc('month', trade_date)) AS months,
                   MIN(trade_date) AS first_day
            FROM valuations
        """))).one()
    logger.info(f"   valuations 現有 {row.stocks:,} 檔、{row.months} 個月（最早 {row.first_day}）")
    logger.info("=" * 60)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="股價淨值比歷史回補（每月取一天）")
    parser.add_argument("years", nargs="?", type=int, default=5, help="往回幾年，預設 5")
    parser.add_argument("--force", action="store_true", help="已經有資料的月份也重抓")
    args = parser.parse_args()
    asyncio.run(run(args.years, args.force))
