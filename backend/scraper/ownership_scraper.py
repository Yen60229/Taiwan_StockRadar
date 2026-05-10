"""
StockRadar - 持股比例爬蟲（HiStock 來源）
資料來源：https://histock.tw/stock/large.aspx?no={code}

抓取項目（最新一筆週資料）：
  - 外資籌碼  → foreign_hold_ratio (%)
  - 董監持股  → director_hold_ratio (%)

寫入目標：ownership_ratios 表
欄位 trust_hold_ratio 暫無可靠來源，維持 NULL。

HiStock 資料說明：
  - 每週更新（集保週資料）
  - 與我們的 chip_concentration 同源（集保）
  - 'tbChip' table 欄位：日期 / 籌碼集中度 / 外資籌碼 / 大戶籌碼 / 董監持股
"""
import asyncio
import logging
import re
from datetime import date, datetime
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

BASE_URL = "https://histock.tw/stock/large.aspx"
TIMEOUT   = 20
CONCURRENCY = 8          # 同時最多 N 個並行請求
REQ_DELAY   = 0.2        # 每個請求後 sleep 秒數（避免 rate limit）
RETRY_COUNT = 2

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
    "Referer": "https://histock.tw/",
}

# 匹配 tbChip table 第一筆資料列
# 欄位：日期 / 籌碼集中度 / 外資籌碼 / 大戶籌碼 / 董監持股
_TABLE_PAT = re.compile(
    r"tbChip.*?"
    r"<tr[^>]*>"
    r"<td[^>]*>(\d{4}/\d{2}/\d{2})</td>"   # g1: date
    r"<td[^>]*>([^<]+)</td>"                 # g2: 籌碼集中度
    r"<td[^>]*>([^<]+)</td>"                 # g3: 外資籌碼
    r"<td[^>]*>([^<]+)</td>"                 # g4: 大戶籌碼
    r"<td[^>]*>([^<]+)</td>",                # g5: 董監持股
    re.DOTALL,
)


def _parse_pct(raw: str) -> Optional[float]:
    """'70.67%' → 70.67；無法解析時回傳 None"""
    try:
        return float(raw.strip().rstrip("%"))
    except (ValueError, AttributeError):
        return None


def _parse_date(raw: str) -> Optional[date]:
    """'2026/04/30' → date(2026,4,30)"""
    try:
        return datetime.strptime(raw.strip(), "%Y/%m/%d").date()
    except ValueError:
        return None


async def _fetch_one(
    client: httpx.AsyncClient,
    sem: asyncio.Semaphore,
    code: str,
) -> Optional[dict]:
    """
    抓取單支股票的持股比例資料
    回傳 dict 或 None（無資料 / 解析失敗）
    """
    url = f"{BASE_URL}?no={code}"
    async with sem:
        for attempt in range(1, RETRY_COUNT + 1):
            try:
                r = await client.get(url, timeout=TIMEOUT)
                if r.status_code != 200:
                    logger.debug(f"[Ownership] {code}: HTTP {r.status_code}")
                    return None

                m = _TABLE_PAT.search(r.text)
                if not m:
                    logger.debug(f"[Ownership] {code}: 找不到 tbChip table")
                    return None

                report_dt    = _parse_date(m.group(1))
                foreign_pct  = _parse_pct(m.group(3))   # 外資籌碼
                director_pct = _parse_pct(m.group(5))   # 董監持股

                if report_dt is None:
                    return None

                return {
                    "stock_code":          code,
                    "report_date":         report_dt,
                    "foreign_hold_ratio":  foreign_pct,
                    "director_hold_ratio": director_pct,
                    "trust_hold_ratio":    None,          # 暫無資料
                }

            except (httpx.TimeoutException, httpx.HTTPError) as e:
                logger.warning(f"[Ownership] {code} attempt {attempt}/{RETRY_COUNT}: {e}")
                if attempt < RETRY_COUNT:
                    await asyncio.sleep(2)
            except Exception as e:
                logger.warning(f"[Ownership] {code} parse error: {e}")
                return None

        return None


async def run_ownership_pipeline(
    codes: list[str],
) -> list[dict]:
    """
    批量抓取 HiStock 持股比例
    回傳 list[dict]，每筆含：
        stock_code, report_date, foreign_hold_ratio, director_hold_ratio, trust_hold_ratio

    Args:
        codes: 要抓取的股票代號清單
    """
    if not codes:
        return []

    logger.info(f"[Ownership] === 開始抓取持股比例，共 {len(codes)} 檔 ===")

    sem     = asyncio.Semaphore(CONCURRENCY)
    results = []
    ok = fail = 0

    async with httpx.AsyncClient(headers=HEADERS, follow_redirects=True) as client:
        tasks = [_fetch_one(client, sem, code) for code in codes]
        # tqdm-friendly: gather with semaphore already controls concurrency
        done = await asyncio.gather(*tasks, return_exceptions=False)

    for item in done:
        if item is not None:
            results.append(item)
            ok += 1
        else:
            fail += 1

    logger.info(
        f"[Ownership] === 完成 ===  成功 {ok} 筆 / 失敗(無資料) {fail} 筆"
    )
    return results


# ── CLI 測試 ─────────────────────────────────────────────────
if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    async def _test():
        test_codes = ["2330", "2454", "3008", "2603", "00665L", "1234"]
        result = await run_ownership_pipeline(test_codes)
        print(f"\n共 {len(result)} 筆：")
        for row in result:
            print(
                f"  {row['stock_code']:8s} "
                f"date={row['report_date']}  "
                f"外資={row['foreign_hold_ratio']}%  "
                f"董監={row['director_hold_ratio']}%"
            )

    asyncio.run(_test())
