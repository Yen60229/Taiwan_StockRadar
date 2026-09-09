"""
StockRadar - TWSE 上市股票爬蟲
資料來源：台灣證券交易所官網 API (www.twse.com.tw/rwd)
抓取項目：
  1. 全部上市股票當日行情（afterTrading/MI_INDEX）
  2. 三大法人買賣超（T86，www.twse.com.tw/rwd）
  3. 上市公司基本資料（產業分類）

20 日均量不在這裡算：個股歷史 API（STOCK_DAY）早已失效（302 → 404），
改由 data_pipeline.compute_avg_vol_from_db() 直接從 DB 的歷史行情算。

⚠️ 不要把當日行情改回 openapi.twse.com.tw 的 STOCK_DAY_ALL：
   那支端點**固定只有前一交易日的資料**（2026-09-10 實測：9/9 收盤後
   等到隔天凌晨，它回報的仍是 9/8），會讓上市股票的收盤價永遠慢一天。
   官網 www.twse.com.tw 的 API 才是當天就更新的，跟 T86 同一家族。
"""
import asyncio
import logging
import re
from datetime import date, timedelta
from typing import Optional

import httpx
import pandas as pd

from scraper import isin

logger = logging.getLogger(__name__)

# ── TWSE 產業別代碼 → 中文名稱 ───────────────────────────────
TWSE_INDUSTRY_MAP: dict[str, str] = {
    "01": "水泥工業",     "02": "食品工業",     "03": "塑膠工業",
    "04": "紡織纖維",     "05": "電機機械",     "06": "電器電纜",
    "07": "化學工業",     "08": "玻璃陶瓷",     "09": "造紙工業",
    "10": "鋼鐵工業",     "11": "橡膠工業",     "12": "汽車工業",
    "13": "建材營造",     "14": "航運業",       "15": "觀光餐旅",
    "16": "金融保險",     "17": "貿易百貨",     "18": "綜合",
    "20": "其他",         "21": "化學工業",     "22": "生技醫療業",
    "23": "油電燃氣業",   "24": "半導體業",     "25": "電腦及週邊設備業",
    "26": "光電業",       "27": "通信網路業",   "28": "電子零組件業",
    "29": "電子通路業",   "30": "資訊服務業",   "31": "其他電子業",
    "32": "文化創意業",   "33": "農業科技業",   "34": "電子商務業",
    "35": "建設業",       "36": "運動休閒業",   "37": "觀光餐旅",
    "38": "居家生活",     "91": "第一上市",
}


def map_industry(code: str) -> str:
    """將 TWSE 產業代碼轉為中文名稱；已是中文或無對應時原值回傳"""
    if not code:
        return "其他"
    return TWSE_INDUSTRY_MAP.get(code.strip().zfill(2), code)


# ── 常數 ─────────────────────────────────────────────────────
MI_INDEX_URL = "https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX"
REQUEST_TIMEOUT = 30       # 秒
RETRY_COUNT = 3
RETRY_DELAY = 5            # 秒

HEADERS = {
    "User-Agent": "StockRadar/1.0 (github.com/Yen60229/Taiwan_StockRadar)",
    "Accept": "application/json",
}


# ── 日期工具 ──────────────────────────────────────────────────
_TITLE_DATE_RE = re.compile(r"(\d{2,3})年(\d{1,2})月(\d{1,2})日")


def _parse_title_date(title: Optional[str]) -> Optional[date]:
    """
    從 MI_INDEX 表格標題取交易日：
      '115年09月09日 每日收盤行情(...)' → date(2026, 9, 9)
    解析不出來回 None，由呼叫端決定要不要 raise（一樣不 fallback 到 today）。
    """
    m = _TITLE_DATE_RE.search(title or "")
    if not m:
        return None
    roc_y, mm, dd = (int(g) for g in m.groups())
    try:
        return date(roc_y + 1911, mm, dd)
    except ValueError:
        return None


# ── HTTP 工具 ─────────────────────────────────────────────────
async def fetch_json(client: httpx.AsyncClient, url: str, params: dict = None) -> list | dict:
    """帶 retry 的 JSON 抓取"""
    for attempt in range(1, RETRY_COUNT + 1):
        try:
            r = await client.get(url, params=params, timeout=REQUEST_TIMEOUT)
            r.raise_for_status()
            # TWSE 無資料時會 redirect 到 404.html 並回 HTTP 200
            ct = r.headers.get("content-type", "")
            if not r.text.strip() or "html" in ct or "404" in str(r.url):
                return []
            return r.json()
        except (httpx.HTTPError, httpx.TimeoutException) as e:
            logger.warning(f"[TWSE] Attempt {attempt}/{RETRY_COUNT} failed: {url} — {e}")
            if attempt < RETRY_COUNT:
                await asyncio.sleep(RETRY_DELAY * attempt)
        except Exception:
            return []
    return []


# ── 1. 當日所有上市股票行情 ───────────────────────────────────
QUOTE_COLUMNS = ["code", "name", "market", "trade_date",
                 "open", "high", "low", "close", "volume"]

# MI_INDEX 回傳的是「多張表」，每日收盤行情只是其中一張（其他是各種指數、
# 漲跌家數統計）。用欄位而不是固定 index 去認表：TWSE 增減表格時 index 會位移。
_QUOTE_TABLE_KEY_FIELD = "證券代號"

_MI_INDEX_COL_MAP = {
    "證券代號": "code",
    "證券名稱": "name",
    "開盤價":   "open",
    "最高價":   "high",
    "最低價":   "low",
    "收盤價":   "close",
    "成交股數": "volume_shares",   # 股，稍後 ÷1000 轉張
}


QUOTE_LOOKBACK_DAYS = 8    # 連假最長約 5-6 天，8 天有安全邊際


async def fetch_all_quotes(
    client: httpx.AsyncClient,
    target: Optional[date] = None,
) -> pd.DataFrame:
    """
    抓最近一個交易日（從 target／今天往前找）的全部上市股票收盤行情。
    回傳欄位：code, name, market, trade_date, open, high, low, close, volume
    volume 單位：張

    來源是官網 afterTrading/MI_INDEX——**當天盤後就有資料**。
    （舊版用 openapi 的 STOCK_DAY_ALL，那支永遠只有前一交易日，見模組 docstring。）

    往前找的理由：MI_INDEX 是「查某一天」的 API，假日查不到東西。
    週末的完整 pipeline 需要拿到最近一個交易日的行情，所以比照 T86
    （fetch_institutional_flow）往前搜。trade_date 一律取自 payload 標題，
    不會因為往前找就把日期標錯。
    """
    target = target or date.today()

    for days_back in range(QUOTE_LOOKBACK_DAYS):
        day = target - timedelta(days=days_back)
        df = await fetch_all_quotes_on(client, day)
        if not df.empty:
            return df

    logger.warning(
        f"[TWSE] MI_INDEX 往前找 {QUOTE_LOOKBACK_DAYS} 天（至 {target}）都沒有行情資料"
    )
    return pd.DataFrame(columns=QUOTE_COLUMNS)


async def fetch_all_quotes_on(
    client: httpx.AsyncClient,
    target: date,
) -> pd.DataFrame:
    """
    抓「指定日期」的上市收盤行情；非交易日回空 DataFrame（不往前找、不 raise）。
    """
    data = await fetch_json(client, MI_INDEX_URL, params={
        "date":     target.strftime("%Y%m%d"),
        "type":     "ALLBUT0999",   # 全部，不含權證/牛熊證
        "response": "json",
    })

    tables = data.get("tables") if isinstance(data, dict) else None
    if not tables:
        logger.debug(f"[TWSE] MI_INDEX {target} 無資料（非交易日）")
        return pd.DataFrame(columns=QUOTE_COLUMNS)

    quote_table = next(
        (t for t in tables if _QUOTE_TABLE_KEY_FIELD in (t.get("fields") or [])),
        None,
    )
    if quote_table is None:
        # 假日也可能回了幾張表卻沒有收盤行情表，所以這裡不 raise；
        # 但用 WARNING 留痕，萬一是 TWSE 改版導致認不到表，log 裡看得出來。
        logger.warning(
            f"[TWSE] MI_INDEX {target} 有 {len(tables)} 張表，"
            f"但找不到含「{_QUOTE_TABLE_KEY_FIELD}」的收盤行情表"
        )
        return pd.DataFrame(columns=QUOTE_COLUMNS)

    # 交易日取自表格標題（不是 date.today()，也不是我們送出去的 target）：
    # 維持 P0-2「日期一律以 payload 為準」的原則。
    trade_date = _parse_title_date(quote_table.get("title"))
    if trade_date is None:
        raise ValueError(
            f"[TWSE] MI_INDEX 表格標題解析不出交易日，拒絕以今日日期寫入："
            f"{quote_table.get('title')!r}"
        )

    df = pd.DataFrame(quote_table.get("data") or [], columns=quote_table["fields"])
    df = df.rename(columns={k: v for k, v in _MI_INDEX_COL_MAP.items() if k in df.columns})

    # 數值清洗（TWSE 用逗號分位，停牌股會是 "--"）
    for col in ["close", "open", "high", "low"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col].astype(str).str.replace(",", ""), errors="coerce")

    if "volume_shares" in df.columns:
        df["volume_shares"] = pd.to_numeric(
            df["volume_shares"].astype(str).str.replace(",", ""), errors="coerce"
        )
        df["volume"] = (df["volume_shares"] / 1000).round(0).astype("Int64")  # 股 → 張

    df["trade_date"] = trade_date
    df["market"] = "TWSE"

    # 只保留普通股（代號為 4 位數字）
    df = df[df["code"].str.match(r"^\d{4}$", na=False)].copy()
    df = df.dropna(subset=["close", "volume"])

    logger.info(f"[TWSE] 當日行情：{len(df)} 檔上市股票（交易日 {trade_date}）")
    return df[QUOTE_COLUMNS]


# ── 2. 三大法人買賣超 ─────────────────────────────────────────
# T86 欄位索引（array-of-arrays 格式，單位：股，需 ÷1000 轉張）
# [0] 證券代號  [4] 外陸資買賣超  [10] 投信買賣超
# [11] 自營商買賣超  [18] 三大法人合計
_T86_URL = "https://www.twse.com.tw/rwd/zh/fund/T86"
_T86_HEADERS = {"User-Agent": "StockRadar/1.0 (research)"}
_CODE_RE = re.compile(r"^\d{4}$")


def _parse_shares_to_lots(v: str) -> float | None:
    """將帶逗號的股數字串轉為張數（÷1000），失敗回傳 None"""
    try:
        return float(str(v).replace(",", "").replace("+", "")) / 1000
    except (ValueError, TypeError):
        return None


async def fetch_institutional_flow(client: httpx.AsyncClient) -> pd.DataFrame:
    """
    抓取 TWSE T86 三大法人買賣超資料。
    回傳欄位：code, trade_date, foreign_net, trust_net, dealer_net, total_net
    單位：張

    API 文件：https://www.twse.com.tw/rwd/zh/fund/T86
    注意：非交易日回傳 stat="很抱歉，沒有符合條件的資料！"，
         故自動往前搜尋最近 7 個日曆日。
    """
    for days_back in range(0, 8):
        target = date.today() - timedelta(days=days_back)
        date_str = target.strftime("%Y%m%d")
        try:
            r = await client.get(
                _T86_URL,
                params={"date": date_str, "selectType": "ALL", "response": "json"},
                headers=_T86_HEADERS,
                timeout=REQUEST_TIMEOUT,
            )
            if r.status_code != 200:
                continue
            payload = r.json()
        except Exception as e:
            logger.warning(f"[TWSE] T86 {date_str} 請求失敗：{e}")
            continue

        if payload.get("stat") != "OK" or not payload.get("data"):
            continue   # 非交易日或無資料，繼續往前找

        records = []
        for row in payload["data"]:
            code = str(row[0]).strip()
            if not _CODE_RE.match(code):
                continue
            records.append({
                "code":        code,
                "trade_date":  target,
                "foreign_net": _parse_shares_to_lots(row[4]),   # 外陸資買賣超
                "trust_net":   _parse_shares_to_lots(row[10]),  # 投信買賣超
                "dealer_net":  _parse_shares_to_lots(row[11]),  # 自營商買賣超
                "total_net":   _parse_shares_to_lots(row[18]),  # 三大法人合計
            })

        df = pd.DataFrame(records)
        logger.info(f"[TWSE] 三大法人（T86）：{len(df)} 筆，交易日 {date_str}")
        return df[["code", "trade_date", "foreign_net", "trust_net", "dealer_net", "total_net"]]

    logger.warning("[TWSE] 三大法人：近 8 日均無交易資料")
    return pd.DataFrame()


# ── 3. 上市公司基本資料（ISIN 網站，產業名稱直接為中文） ──────
# TWSE OpenAPI (t187ap03_L) 的產業別欄位為內部數字代碼，
# 與傳統 01-38 分類不一致，會造成系統性錯位。
# 改從 ISIN 網站（strMode=2）抓取，直接取得正確中文產業名稱。
_ISIN_TWSE_URL = "https://isin.twse.com.tw/isin/C_public.jsp?strMode=2"
TWSE_CODE_PATTERN = r"^\d{4}$"     # 上市普通股為 4 碼
_ISIN_HEADERS  = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-TW,zh;q=0.9",
}

async def fetch_company_info(client: httpx.AsyncClient) -> pd.DataFrame:
    """
    從 ISIN 網站抓取上市公司基本資料（產業名稱直接為中文，不需代碼轉換）。
    回傳欄位：code, name, short_name, industry

    資料來源：https://isin.twse.com.tw/isin/C_public.jsp?strMode=2
    ・編碼：Big5
    ・每筆普通股 7 個 <td>：
        cells[0] = "代號　名稱"（全型空格分隔）
        cells[4] = 產業別（直接中文）
    """
    try:
        r = await client.get(_ISIN_TWSE_URL, headers=_ISIN_HEADERS, timeout=30)
        html = r.content.decode("big5", errors="replace")
    except Exception as e:
        logger.warning(f"[TWSE] ISIN 網站抓取失敗：{e}")
        return isin.empty_frame()

    df = isin.parse_isin_html(html, TWSE_CODE_PATTERN)
    if df.empty:
        logger.warning("[TWSE] ISIN 解析結果為空（網頁結構可能變動）")
        return df

    logger.info(f"[TWSE] ISIN 公司基本資料：{len(df)} 家上市股票")
    return df


# ── 主流程 ────────────────────────────────────────────────────
async def run_twse_pipeline() -> dict:
    """
    完整 TWSE 抓取流程，回傳彙整後的 DataFrames
    """
    async with httpx.AsyncClient(headers=HEADERS, follow_redirects=True) as client:
        logger.info("═" * 50)
        logger.info("[TWSE] 開始抓取上市股票資料")

        # Step 1: 當日行情
        quotes_df = await fetch_all_quotes(client)

        # Step 2: 初步過濾（當日量 >= 1500 張，保留緩衝）
        candidates = quotes_df[quotes_df["volume"] >= 1500]["code"].tolist()
        logger.info(f"[TWSE] 初步候選股（當日量≥1500張）：{len(candidates)} 檔")

        # Step 3: 均量由 data_pipeline.compute_avg_vol_from_db() 從 DB 計算
        #         （個股歷史 API 已失效，見模組 docstring）
        quotes_df["avg_vol_20d"] = None  # 留空，pipeline 會從 DB 填入

        # Step 4: 三大法人
        inst_df = await fetch_institutional_flow(client)

        # Step 5: 公司基本資料
        company_df = await fetch_company_info(client)

        logger.info("═" * 50)

        return {
            "quotes":    quotes_df,
            "inst_flow": inst_df,
            "companies": company_df,
        }


# ── CLI 測試用 ────────────────────────────────────────────────

# ── 4. 指定日期的三大法人（歷史回補 / 每日排程用） ────────────
def _parse_t86_payload(payload: dict, target: date) -> pd.DataFrame:
    """把 T86 的 JSON payload 解析成標準欄位；非交易日回傳空 DataFrame"""
    if payload.get("stat") != "OK" or not payload.get("data"):
        return pd.DataFrame()

    records = []
    for row in payload["data"]:
        code = str(row[0]).strip()
        if not _CODE_RE.match(code):
            continue
        records.append({
            "code":        code,
            "trade_date":  target,
            "foreign_net": _parse_shares_to_lots(row[4]),   # 外陸資買賣超（不含外資自營商）
            "trust_net":   _parse_shares_to_lots(row[10]),  # 投信買賣超
            "dealer_net":  _parse_shares_to_lots(row[11]),  # 自營商買賣超
            "total_net":   _parse_shares_to_lots(row[18]),  # 三大法人合計
        })
    if not records:
        return pd.DataFrame()
    return pd.DataFrame(records)[
        ["code", "trade_date", "foreign_net", "trust_net", "dealer_net", "total_net"]
    ]


async def fetch_institutional_flow_on(
    client: httpx.AsyncClient, target: date
) -> pd.DataFrame:
    """
    抓「指定交易日」的 TWSE 三大法人買賣超。
    非交易日（假日 / 尚未公布）回傳空 DataFrame，不往前找、不 raise。
    """
    date_str = target.strftime("%Y%m%d")
    try:
        r = await client.get(
            _T86_URL,
            params={"date": date_str, "selectType": "ALL", "response": "json"},
            headers=_T86_HEADERS,
            timeout=REQUEST_TIMEOUT,
        )
        if r.status_code != 200:
            return pd.DataFrame()
        payload = r.json()
    except Exception as e:
        logger.warning(f"[TWSE] T86 {date_str} 請求失敗：{e}")
        return pd.DataFrame()

    return _parse_t86_payload(payload, target)

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    async def _test():
        result = await run_twse_pipeline()
        print("\n🎯 篩選結果（前10筆）：")
        print(result["filtered"][["code", "name", "close", "volume", "avg_vol_20d"]].head(10).to_string(index=False))
        print(f"\n✅ TWSE 完成：共 {len(result['filtered'])} 檔符合日均量條件")

    asyncio.run(_test())
