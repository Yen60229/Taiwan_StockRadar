"""
StockRadar - 集保結算所籌碼集中度爬蟲
資料來源：台灣集中保管結算所 (tdcc.com.tw)
抓取項目：持股分級分佈 → 計算 400 張以上持股人數比例

更新頻率：每週五公告（週四資料）
執行策略：只抓日均量已達標的候選股，降低請求量

修正說明：
  - 加入 SYNCHRONIZER_TOKEN（Spring Security CSRF）機制
  - 用同一個 AsyncClient session 維持 cookie
  - 移除對 table.hasBorder class 的依賴
  - firDate 從頁面隱藏欄位讀取（而非自行推算）
"""
import asyncio
import logging
import re
from datetime import date, timedelta
from typing import Optional

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

TDCC_URL      = "https://www.tdcc.com.tw/portal/zh/smWeb/qryStock"
REQUEST_DELAY = 1.5     # 每筆請求間隔（秒），避免被封鎖
BATCH_SIZE    = 10      # 每批並行請求數
RETRY_COUNT   = 3
RETRY_DELAY   = 8
TOKEN_REFRESH = 50      # 每處理 N 筆後重新取得 CSRF token

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/124.0.0.0 Safari/537.36",
    "Content-Type": "application/x-www-form-urlencoded",
    "Referer": "https://www.tdcc.com.tw/portal/zh/smWeb/qryStock",
    "Origin":  "https://www.tdcc.com.tw",
    "Accept":  "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-TW,zh;q=0.9",
}

THRESHOLD_SHARES = 400  # 張，集中度門檻


def get_latest_week_date() -> str:
    """
    【備用】取得上一個完整週四的日期字串 YYYYMMDD。
    集保每週四發布資料（非週五）。

    ⚠️ 此函式僅作 Session init 失敗時的 fallback。
    正式流程由 init_session() 從頁面 firDate hidden input 讀取，
    可正確處理假日停市的情況（如勞動節、農曆春節等）。
    """
    today = date.today()
    # 集保發布日為週四（weekday=3）
    days_since_thursday = (today.weekday() - 3) % 7
    if days_since_thursday == 0:
        days_since_thursday = 7   # 今天就是週四，取上週四（資料可能尚未完整）
    last_thursday = today - timedelta(days=days_since_thursday)
    return last_thursday.strftime("%Y%m%d")


async def init_session(client: httpx.AsyncClient) -> dict:
    """
    GET 集保查詢首頁，取得：
      - SYNCHRONIZER_TOKEN (Spring Security CSRF token)
      - SYNCHRONIZER_URI / firDate（隱藏欄位）
      - latest_date = firDate（頁面 hidden input，即集保最新已發布週日期）
    同一個 client 的 cookie 會自動帶入後續 POST。
    """
    for attempt in range(1, RETRY_COUNT + 1):
        try:
            r = await client.get(TDCC_URL, headers=HEADERS, timeout=20)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")

            def _val(name: str) -> str:
                inp = soup.find("input", {"name": name})
                return inp.get("value", "") if inp else ""

            token   = _val("SYNCHRONIZER_TOKEN")
            syn_uri = _val("SYNCHRONIZER_URI") or "/portal/zh/smWeb/qryStock"
            fir_date = _val("firDate") or get_latest_week_date()

            # latest_date 直接使用 firDate（頁面 hidden input），
            # 這是集保已實際發布的最新週日期。
            # scaDate 下拉選單的 options[0] 可能包含尚未發布的未來日期，
            # 用 firDate 才能確保查詢到有效資料。
            latest_date = fir_date

            logger.info(
                f"[TDCC] Session 初始化：latest_date={latest_date}, "
                f"token={'✅' if token else '❌ 未取得'}"
            )
            return {
                "SYNCHRONIZER_TOKEN": token,
                "SYNCHRONIZER_URI":   syn_uri,
                "firDate":            fir_date,
                "latest_date":        latest_date,
            }
        except Exception as e:
            logger.warning(f"[TDCC] Session init 失敗 嘗試 {attempt}/{RETRY_COUNT}: {e}")
            if attempt < RETRY_COUNT:
                await asyncio.sleep(RETRY_DELAY * attempt)

    logger.error("[TDCC] 無法初始化 Session，將使用空 token 繼續")
    return {
        "SYNCHRONIZER_TOKEN": "",
        "SYNCHRONIZER_URI":   "/portal/zh/smWeb/qryStock",
        "firDate":            get_latest_week_date(),
        "latest_date":        get_latest_week_date(),
    }


def parse_holding_table(html: str) -> Optional[dict]:
    """
    解析集保 HTML 持股分級表，計算 400 張以上集中度。

    集保 HTML table 結構（2025 年後版本，5 欄）：
      序 | 持股/單位數分級 | 人數 | 股數/單位數 | 占集保庫存數比例(%)

    識別邏輯：找表頭含「人數」的 table，動態定位各欄 index。
    不依賴 CSS class，向前相容舊版 4 欄結構。
    """
    soup = BeautifulSoup(html, "html.parser")

    def _col_idx(header_cells: list, *keywords: str) -> int:
        """從表頭 cells 找第一個包含任一關鍵字的欄位 index；找不到回 -1"""
        for i, cell in enumerate(header_cells):
            text = cell.get_text(strip=True)
            if any(kw in text for kw in keywords):
                return i
        return -1

    target_table = None
    level_idx = holders_idx = shares_idx = ratio_idx = -1

    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if len(rows) < 10:
            continue
        # 以表頭列定位欄位
        header_cells = rows[0].find_all(["td", "th"])
        hi = _col_idx(header_cells, "人數")
        li = _col_idx(header_cells, "分級", "持股")
        si = _col_idx(header_cells, "股數", "單位數")
        ri = _col_idx(header_cells, "比例", "%")
        if hi == -1:
            continue
        # 確認有足夠數字列
        data_rows = sum(
            1 for row in rows[1:]
            if len(row.find_all(["td", "th"])) > hi
            and row.find_all(["td", "th"])[hi].get_text(strip=True).replace(",", "").isdigit()
        )
        if data_rows >= 5:
            target_table = table
            level_idx, holders_idx, shares_idx, ratio_idx = li, hi, si, ri
            break

    if target_table is None:
        logger.debug("[TDCC] 找不到持股分級表格（可能返回表單頁，CSRF token 可能失效）")
        return None

    rows = target_table.find_all("tr")
    holders_400up  = 0
    shares_400up   = 0
    holders_total  = 0
    shares_total   = 0
    conc_ratio_sum = 0.0          # 直接加總「占集保庫存數比例(%)」欄
    threshold_shares_unit = THRESHOLD_SHARES * 1000  # 400,000 股

    for row in rows[1:]:  # 跳過表頭
        cells = row.find_all(["td", "th"])
        if len(cells) <= max(level_idx, holders_idx):
            continue

        level_text   = cells[level_idx].get_text(strip=True) if level_idx >= 0 else ""
        holders_text = cells[holders_idx].get_text(strip=True).replace(",", "")
        shares_text  = (cells[shares_idx].get_text(strip=True).replace(",", "")
                        if shares_idx >= 0 and len(cells) > shares_idx else "0")
        ratio_text   = (cells[ratio_idx].get_text(strip=True).replace(",", "")
                        if ratio_idx >= 0 and len(cells) > ratio_idx else "0")

        # 跳過「合　計」合計列（避免雙重計算）
        if "計" in level_text:
            continue

        if not holders_text.isdigit():
            continue

        holders = int(holders_text)
        shares  = int(shares_text) if shares_text.isdigit() else 0

        holders_total += holders
        shares_total  += shares

        # 判斷是否 >= 400 張（400,000 股）
        # 集保級距文字範例：
        #   "400,001-600,000"（股）= 400~600 張
        #   "1,000,001以上"
        nums = re.findall(r"[\d,]+", level_text)
        if nums:
            try:
                min_val = int(nums[0].replace(",", ""))
                if min_val >= threshold_shares_unit:
                    holders_400up  += holders
                    shares_400up   += shares
                    # 正確集中度：直接加總該級距的「占集保庫存數比例」
                    try:
                        conc_ratio_sum += float(ratio_text)
                    except ValueError:
                        pass
            except ValueError:
                pass

    if holders_total == 0:
        return None

    # conc_ratio = 400張以上各級距的股數佔集保庫存比例加總
    # （即「持股400張以上的人所持有的股數 / 全部集保股數」）
    conc_ratio = round(conc_ratio_sum, 2)
    return {
        "holders_400up": holders_400up,
        "holders_total": holders_total,
        "shares_400up":  shares_400up // 1000,  # 股 → 張
        "conc_ratio":    conc_ratio,
    }


async def fetch_chip_one(
    client: httpx.AsyncClient,
    stock_code: str,
    week_date: str,
    session: dict,
) -> Optional[dict]:
    """
    抓取單一股票的集保籌碼資料。
    session 必須包含 SYNCHRONIZER_TOKEN / SYNCHRONIZER_URI / firDate。
    """
    payload = {
        "SYNCHRONIZER_TOKEN": session["SYNCHRONIZER_TOKEN"],
        "SYNCHRONIZER_URI":   session["SYNCHRONIZER_URI"],
        "method":             "submit",
        "firDate":            session["firDate"],
        "sqlMethod":          "StockNo",   # 小寫，與表單 name 一致
        "stockNo":            stock_code,   # 小寫，與表單 name 一致
        "scaDate":            week_date,    # select name=scaDate（無複數）
    }

    for attempt in range(1, RETRY_COUNT + 1):
        try:
            r = await client.post(TDCC_URL, data=payload, headers=HEADERS, timeout=20)
            r.raise_for_status()

            # Spring Synchronizer Token 每次 POST 後更新 — 從 response 取新 token
            resp_soup = BeautifulSoup(r.text, "html.parser")
            new_token_inp = resp_soup.find("input", {"name": "SYNCHRONIZER_TOKEN"})
            if new_token_inp:
                session["SYNCHRONIZER_TOKEN"] = new_token_inp.get("value", session["SYNCHRONIZER_TOKEN"])
                payload["SYNCHRONIZER_TOKEN"] = session["SYNCHRONIZER_TOKEN"]

            parsed = parse_holding_table(r.text)
            if parsed is None:
                logger.debug(f"[TDCC] {stock_code}: 無法解析（可能無資料或 token 失效）")
                return None

            return {
                "stock_code": stock_code,
                "week_date":  date.fromisoformat(
                    f"{week_date[:4]}-{week_date[4:6]}-{week_date[6:8]}"
                ),
                **parsed,
            }

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429:
                wait = RETRY_DELAY * attempt * 2
                logger.warning(f"[TDCC] {stock_code} 被限流，等待 {wait}s...")
                await asyncio.sleep(wait)
            else:
                logger.warning(f"[TDCC] {stock_code} HTTP {e.response.status_code}")
                return None
        except Exception as e:
            logger.warning(f"[TDCC] {stock_code} 嘗試 {attempt}/{RETRY_COUNT}: {e}")
            if attempt < RETRY_COUNT:
                await asyncio.sleep(RETRY_DELAY * attempt)

    return None


async def fetch_chip_batch(
    stock_codes: list[str],
    week_date: Optional[str] = None,
    min_conc: float = 40.0,
) -> list[dict]:
    """
    批量抓取多檔股票的籌碼集中度。

    Args:
        stock_codes: 要查詢的股票代號清單
        week_date:   集保週日期 YYYYMMDD（None 則從頁面讀取最新日期）
        min_conc:    只回傳集中度 >= 此值的資料

    Returns:
        符合條件的籌碼資料清單
    """
    async with httpx.AsyncClient(follow_redirects=True) as client:
        # 初始化 session（取 CSRF token + firDate）
        session = await init_session(client)

        # 若未指定週日期，使用頁面 scaDate select 的第一個選項（最新已發布日期）
        if week_date is None:
            week_date = session["latest_date"]

        logger.info(f"[TDCC] 開始抓取 {len(stock_codes)} 檔，週日期：{week_date}")
        logger.info(f"[TDCC] 預估耗時：{len(stock_codes) * REQUEST_DELAY / 60:.1f} 分鐘")

        results = []
        total = len(stock_codes)

        for i in range(0, total, BATCH_SIZE):
            batch = stock_codes[i:i + BATCH_SIZE]

            # 每 TOKEN_REFRESH 筆重新取得 CSRF token（防 session 過期）
            if i > 0 and i % TOKEN_REFRESH == 0:
                logger.info(f"[TDCC] 重新取得 CSRF token（已處理 {i} 筆）")
                session = await init_session(client)

            for j, code in enumerate(batch):
                result = await fetch_chip_one(client, code, week_date, session)

                if result and result["conc_ratio"] >= min_conc:
                    results.append(result)
                    logger.debug(
                        f"[TDCC] ✅ {code} 籌碼集中度 {result['conc_ratio']}%"
                    )

                current = i + j + 1
                if current % 50 == 0 or current == total:
                    logger.info(
                        f"[TDCC] 進度：{current}/{total} "
                        f"({current/total*100:.0f}%) | 符合：{len(results)} 檔"
                    )

                if j < len(batch) - 1:
                    await asyncio.sleep(REQUEST_DELAY)

            if i + BATCH_SIZE < total:
                await asyncio.sleep(REQUEST_DELAY * 2)

    logger.info(f"[TDCC] 完成！籌碼集中度≥{min_conc}%：{len(results)}/{total} 檔")
    return results


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    async def _test():
        test_codes = ["2330", "2317", "2454", "2881", "2412"]
        print("📅 使用頁面最新週日期（自動從集保網站讀取）")

        results = await fetch_chip_batch(test_codes, week_date=None, min_conc=0.0)

        print("\n📊 籌碼集中度結果：")
        for r in results:
            print(
                f"  {r['stock_code']} | "
                f"集中度 {r['conc_ratio']:5.1f}% | "
                f"400張以上 {r['holders_400up']:5d} 人 / "
                f"總計 {r['holders_total']:6d} 人"
            )
        if not results:
            print("  （無結果 — 請確認 CSRF token 是否正常取得）")

    asyncio.run(_test())
