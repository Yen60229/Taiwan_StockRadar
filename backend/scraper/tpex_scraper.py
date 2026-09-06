"""
StockRadar - TPEX 上櫃股票爬蟲
資料來源：
  1. 當日行情／三大法人：櫃買中心 OpenAPI (tpex.org.tw/openapi)
  2. 公司基本資料（簡稱＋產業）：ISIN 網站 (isin.twse.com.tw/isin/C_public.jsp?strMode=4)
     ※ TPEX OpenAPI 被 Cloudflare 封鎖，改用 ISIN 網站替代
抓取項目：
  1. 全部上櫃股票當日行情
  2. 三大法人買賣超
  3. 上櫃公司基本資料（簡稱＋產業分類）
"""
import asyncio
import logging
import re
from datetime import date
from typing import Optional

import httpx
import pandas as pd
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

BASE_URL    = "https://www.tpex.org.tw/openapi/v1"
MIN_AVG_VOL = 2000
RETRY_COUNT = 3
RETRY_DELAY = 5
HEADERS = {
    "User-Agent": "StockRadar/1.0",
    "Accept": "application/json",
}


async def fetch_json(client: httpx.AsyncClient, url: str, params: dict = None) -> list | dict:
    for attempt in range(1, RETRY_COUNT + 1):
        try:
            r = await client.get(url, params=params, timeout=30)
            r.raise_for_status()
            ct = r.headers.get("content-type", "")
            if not r.text.strip() or "html" in ct:
                return []
            return r.json()
        except Exception as e:
            logger.warning(f"[TPEX] Attempt {attempt}/{RETRY_COUNT} failed: {url} — {e}")
            if attempt < RETRY_COUNT:
                await asyncio.sleep(RETRY_DELAY * attempt)
    return []


# ── 1. 當日上櫃行情 ───────────────────────────────────────────
async def fetch_all_quotes(client: httpx.AsyncClient) -> pd.DataFrame:
    """
    回傳欄位：code, name, market, trade_date, open, high, low, close, volume（張）
    """
    url = f"{BASE_URL}/tpex_mainboard_daily_close_quotes"
    data = await fetch_json(client, url)
    df = pd.DataFrame(data)

    if df.empty:
        logger.warning("[TPEX] 當日行情為空")
        return pd.DataFrame()

    logger.info(f"[TPEX] 原始欄位：{list(df.columns)}")

    # TPEX 欄位名稱（可能因版本不同，做相容處理）
    col_candidates = {
        "code":   ["SecuritiesCompanyCode", "Code", "stock_code"],
        "name":   ["CompanyName", "Name", "company_name"],
        "close":  ["ClosingPrice", "Close", "closing_price"],
        "open":   ["OpeningPrice", "Open"],
        "high":   ["HighestPrice", "High"],
        "low":    ["LowestPrice",  "Low"],
        "volume": [
            "TradeVolume", "Volume", "trade_volume",
            "TradingVolume", "TradingShares", "TradeShares",
            "CombinedVolume", "成交量", "成交股數",
        ],
    }

    rename_map = {}
    for target, candidates in col_candidates.items():
        for c in candidates:
            if c in df.columns:
                rename_map[c] = target
                break

    df = df.rename(columns=rename_map)

    # 找不到已知候選時，嘗試模糊比對 volume
    if "volume" not in df.columns:
        vol_col = next(
            (c for c in df.columns if "vol" in c.lower() or "volume" in c.lower()),
            None,
        )
        if vol_col:
            logger.warning(f"[TPEX] volume 欄位用模糊比對：{vol_col}")
            df = df.rename(columns={vol_col: "volume"})
        else:
            logger.error(f"[TPEX] 找不到 volume 欄位，實際欄位：{list(df.columns)}")
            return pd.DataFrame()

    for col in ["close", "open", "high", "low"]:
        if col in df.columns:
            df[col] = pd.to_numeric(
                df[col].astype(str).str.replace(",", ""), errors="coerce"
            )

    if "volume" in df.columns:
        df["volume_shares"] = pd.to_numeric(
            df["volume"].astype(str).str.replace(",", ""), errors="coerce"
        )
        df["volume"] = (df["volume_shares"] / 1000).round(0).astype("Int64")

    # 交易日以 payload 的 Date 為準（非 date.today()），假日執行不污染時序表
    if "Date" not in df.columns or df.empty:
        raise ValueError("[TPEX] 行情 payload 缺少 Date 欄位，拒絕以今日日期寫入")
    df["trade_date"] = _roc_to_date(str(df["Date"].iloc[0]))
    df["market"] = "TPEX"

    # 只保留 4~5 位數代號的普通股
    df = df[df["code"].astype(str).str.match(r"^\d{4,5}$", na=False)].copy()
    df = df.dropna(subset=["close", "volume"])

    logger.info(f"[TPEX] 當日行情：{len(df)} 檔上櫃股票")
    return df[["code", "name", "market", "trade_date", "open", "high", "low", "close", "volume"]]


# ── 2. 三大法人買賣超 ─────────────────────────────────────────
# 新版 API：tpex_3insti_daily_trading（OpenAPI v1，list of dicts）
# 值為「股」單位，需 ÷1000 轉張；日期為民國格式（如 1150508 = 2026-05-08）
_TPEX_3INSTI_URL = "https://www.tpex.org.tw/openapi/v1/tpex_3insti_daily_trading"
_TPEX_CODE_RE    = re.compile(r"^\d{4,5}$")

# API 欄位名稱（注意 key 含空格，為 TPEX 原始設計）
_FK_DIFF  = "ForeignInvestorsInclude MainlandAreaInvestors-Difference"
_TRUST_DIFF = "SecuritiesInvestmentTrustCompanies-Difference"
_DEALER_DIFF = "Dealers-Difference"
_TOTAL_DIFF  = "TotalDifference"


def _roc_to_date(roc_str: str) -> date:
    """民國年字串（如 '1150508'）→ Python date；解析失敗 raise，不再 fallback 到今日"""
    try:
        s = str(roc_str).strip()
        return date(int(s[:-4]) + 1911, int(s[-4:-2]), int(s[-2:]))
    except (ValueError, IndexError, TypeError):
        raise ValueError(f"[TPEX] 無法解析民國日期：{roc_str!r}")


def _to_lots(v) -> float | None:
    """股數字串 → 張數（÷1000）"""
    try:
        return float(str(v).replace(",", "").replace("+", "")) / 1000
    except (ValueError, TypeError):
        return None


async def fetch_institutional_flow(client: httpx.AsyncClient) -> pd.DataFrame:
    """
    抓取 TPEX 三大法人買賣超。
    回傳欄位：code, trade_date, foreign_net, trust_net, dealer_net, total_net
    單位：張

    API 文件：https://www.tpex.org.tw/openapi/v1/tpex_3insti_daily_trading
    （無需日期參數，永遠回傳最新交易日）
    """
    data = await fetch_json(client, _TPEX_3INSTI_URL)

    if not data or not isinstance(data, list):
        logger.warning("[TPEX] 三大法人資料為空")
        return pd.DataFrame()

    # 解析交易日期（取第一筆的 Date 欄）
    trade_date = _roc_to_date(str(data[0].get("Date", "")))

    records = []
    for item in data:
        code = str(item.get("SecuritiesCompanyCode", "")).strip()
        if not _TPEX_CODE_RE.match(code):
            continue
        records.append({
            "code":        code,
            "trade_date":  trade_date,
            "foreign_net": _to_lots(item.get(_FK_DIFF)),
            "trust_net":   _to_lots(item.get(_TRUST_DIFF)),
            "dealer_net":  _to_lots(item.get(_DEALER_DIFF)),
            "total_net":   _to_lots(item.get(_TOTAL_DIFF)),
        })

    df = pd.DataFrame(records)
    logger.info(f"[TPEX] 三大法人（OpenAPI）：{len(df)} 筆，交易日 {trade_date}")
    return df[["code", "trade_date", "foreign_net", "trust_net", "dealer_net", "total_net"]]


# ── 3. 上櫃公司基本資料（ISIN 網站） ─────────────────────────
# TPEX OpenAPI (tpex_mainboard_companies_information) 被 Cloudflare 封鎖（302 重導），
# 改從 ISIN 網站抓取，ISIN 網站同時提供公司簡稱與產業分類。
_ISIN_TPEX_URL = "https://isin.twse.com.tw/isin/C_public.jsp?strMode=4"
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
    從 ISIN 網站抓取上櫃公司基本資料。
    回傳欄位：code, name, short_name, industry

    資料來源：https://isin.twse.com.tw/isin/C_public.jsp?strMode=4
    ・編碼：Big5
    ・每筆普通股 6 個 <td>：
        cells[0] = "代號　名稱"
        cells[4] = 產業別
    """
    _EMPTY = pd.DataFrame(columns=["code", "name", "short_name", "industry"])
    try:
        r = await client.get(_ISIN_TPEX_URL, headers=_ISIN_HEADERS, timeout=30)
        html = r.content.decode("big5", errors="replace")
    except Exception as e:
        logger.warning(f"[TPEX] ISIN 網站抓取失敗：{e}")
        return _EMPTY

    soup = BeautifulSoup(html, "html.parser")
    records = []
    for row in soup.find_all("tr"):
        cells = [td.get_text(strip=True) for td in row.find_all("td")]
        # 資料列共 7 格：有價證券代號及名稱 | ISIN | 上市日 | 市場別 | 產業別 | CFICode | 備註
        if len(cells) != 7:
            continue
        raw = cells[0]
        # cells[0] 格式：「代號　名稱」（全型空格 U+3000 分隔）
        if "　" not in raw:
            continue
        parts = raw.split("　", 1)
        if len(parts) != 2:
            continue
        code, name = parts[0].strip(), parts[1].strip()
        # 只保留 4~5 位數普通股代號（排除 7xxxxx 權證、ETF 等）
        if not re.match(r"^\d{4,5}$", code):
            continue
        industry = cells[4].strip() or "其他"
        records.append({
            "code":       code,
            "name":       name,
            "short_name": name,   # ISIN 的名稱本身已是市場簡稱
            "industry":   industry,
        })

    df = pd.DataFrame(records)
    if df.empty:
        logger.warning("[TPEX] ISIN 解析結果為空（網頁結構可能變動）")
        return _EMPTY

    logger.info(f"[TPEX] ISIN 公司基本資料：{len(df)} 家上櫃股票")
    return df[["code", "name", "short_name", "industry"]]


# ── 主流程 ────────────────────────────────────────────────────
async def run_tpex_pipeline() -> dict:
    async with httpx.AsyncClient(headers=HEADERS, follow_redirects=True) as client:
        logger.info("═" * 50)
        logger.info("[TPEX] 開始抓取上櫃股票資料")

        quotes_df  = await fetch_all_quotes(client)
        inst_df    = await fetch_institutional_flow(client)
        company_df = await fetch_company_info(client)

        filtered = quotes_df[quotes_df["volume"] >= MIN_AVG_VOL].copy() if not quotes_df.empty else quotes_df
        logger.info(f"[TPEX] 當日量≥{MIN_AVG_VOL}張（初步）：{len(filtered)} 檔")
        logger.info("═" * 50)

        return {
            "quotes":    quotes_df,
            "filtered":  filtered,
            "inst_flow": inst_df,
            "companies": company_df,
        }



# ── 4. 指定日期的三大法人（歷史回補 / 每日排程用） ────────────
# OpenAPI 的 tpex_3insti_daily_trading 只回「最新一天」，無法指定日期。
# 歷史資料改用櫃買中心網站的 dailyTrade 端點（民國日期，如 115/09/04）。
_TPEX_INSTI_BY_DATE_URL = "https://www.tpex.org.tw/www/zh-tw/insti/dailyTrade"

# 欄位索引（已用實際資料驗算：[10] + [13] + [22] == [23]）
_TPEX_COL_FOREIGN = 10   # 外資及陸資買賣超（合計）
_TPEX_COL_TRUST   = 13   # 投信買賣超
_TPEX_COL_DEALER  = 22   # 自營商買賣超（合計）
_TPEX_COL_TOTAL   = 23   # 三大法人買賣超合計


def _to_roc_slash(d: date) -> str:
    """date → 民國斜線格式，如 2026-09-04 → '115/09/04'"""
    return f"{d.year - 1911}/{d.month:02d}/{d.day:02d}"


async def fetch_institutional_flow_on(
    client: httpx.AsyncClient, target: date
) -> pd.DataFrame:
    """
    抓「指定交易日」的 TPEX 三大法人買賣超。
    非交易日回傳空 DataFrame，不 raise。
    """
    try:
        r = await client.get(
            _TPEX_INSTI_BY_DATE_URL,
            params={"type": "Daily", "sect": "EW",
                    "date": _to_roc_slash(target), "id": "", "response": "json"},
            headers=_ISIN_HEADERS,   # 需要瀏覽器 UA，否則被 Cloudflare 擋
            timeout=30,
        )
        if r.status_code != 200:
            return pd.DataFrame()
        payload = r.json()
    except Exception as e:
        logger.warning(f"[TPEX] 三大法人 {target} 請求失敗：{e}")
        return pd.DataFrame()

    tables = payload.get("tables") or []
    if not tables or not tables[0].get("data"):
        return pd.DataFrame()

    table = tables[0]
    # 用回應自己回報的日期，避免要到的日期與實際資料不符
    actual = target
    if table.get("date"):
        try:
            y, m, dd = str(table["date"]).split("/")
            actual = date(int(y) + 1911, int(m), int(dd))
        except (ValueError, TypeError):
            pass
    if actual != target:
        logger.warning(f"[TPEX] 要求 {target} 但回應日期為 {actual}，略過")
        return pd.DataFrame()

    records = []
    for row in table["data"]:
        code = str(row[0]).strip()
        if not _TPEX_CODE_RE.match(code):
            continue
        records.append({
            "code":        code,
            "trade_date":  actual,
            "foreign_net": _to_lots(row[_TPEX_COL_FOREIGN]),
            "trust_net":   _to_lots(row[_TPEX_COL_TRUST]),
            "dealer_net":  _to_lots(row[_TPEX_COL_DEALER]),
            "total_net":   _to_lots(row[_TPEX_COL_TOTAL]),
        })
    if not records:
        return pd.DataFrame()
    return pd.DataFrame(records)[
        ["code", "trade_date", "foreign_net", "trust_net", "dealer_net", "total_net"]
    ]

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    async def _test():
        result = await run_tpex_pipeline()
        if not result["quotes"].empty:
            print("\n📋 上櫃行情（前5筆）：")
            print(result["quotes"][["code","name","close","volume"]].head().to_string(index=False))
        print(f"\n✅ TPEX 完成：共 {len(result['filtered'])} 檔當日量達標")

    asyncio.run(_test())
