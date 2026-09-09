"""
StockRadar - 回補「單一交易日」的上市（TWSE）行情

用途：
  修 openapi STOCK_DAY_ALL 慢一天的 bug（2026-09-10）時，DB 裡最後一個
  交易日的 TWSE 行情會缺一天——舊程式每天寫的都是前一交易日的資料，
  換成當日端點之後，中間那天不會有人去補。這支就是拿來補洞的。

  也可以在任何「某天排程沒跑成功」的情況重跑，冪等（upsert）。

執行方式（在 scheduler / api container 內，backend 目錄下）：
  python -m scripts.backfill_twse_day 2026-09-09
  python -m scripts.backfill_twse_day 2026-09-09 2026-09-10   # 補多天

補完會一併重算那幾天的 20 日均量。
"""
import asyncio
import logging
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx

from models.database import AsyncSessionLocal
from pipeline.data_pipeline import refresh_avg_vol, upsert_daily_quotes
from scraper.twse_scraper import HEADERS, fetch_all_quotes_on

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("backfill_twse_day")


async def backfill(targets: list[date]) -> int:
    written = 0
    async with httpx.AsyncClient(headers=HEADERS, follow_redirects=True) as client:
        for target in targets:
            df = await fetch_all_quotes_on(client, target)
            if df.empty:
                logger.warning(f"[{target}] 無資料（非交易日？），跳過")
                continue

            # 日期以 payload 為準：萬一 TWSE 回了別天的資料，寧可看得出來也不要默默寫錯
            payload_date = df["trade_date"].iloc[0]
            if payload_date != target:
                logger.error(
                    f"[{target}] TWSE 回傳的交易日是 {payload_date}，不一致，跳過不寫入"
                )
                continue

            async with AsyncSessionLocal() as session:
                n = await upsert_daily_quotes(session, df)
                await refresh_avg_vol(session, target)
            logger.info(f"[{target}] 寫入 {n} 檔上市行情，並重算 20 日均量")
            written += n
    return written


def _parse_args(argv: list[str]) -> list[date]:
    if not argv:
        raise SystemExit("用法：python -m scripts.backfill_twse_day YYYY-MM-DD [YYYY-MM-DD ...]")
    return [date.fromisoformat(a) for a in argv]


if __name__ == "__main__":
    targets = _parse_args(sys.argv[1:])
    total = asyncio.run(backfill(targets))
    print(f"\n✅ 完成，共寫入 {total} 筆")
