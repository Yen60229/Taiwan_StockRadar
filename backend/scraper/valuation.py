"""
StockRadar - 本益比、殖利率、股價淨值比（兩市）

資料來源（2026-11-07 實測）：
  上市：www.twse.com.tw/rwd/zh/afterTrading/BWIBBU_d
  上櫃：www.tpex.org.tw/www/zh-tw/afterTrading/peQryDate

兩邊的寫法不一樣，這裡統一成同一種格式再交給 pipeline：

  | 欄位         | 上市原始值   | 上櫃原始值   | 統一後   |
  |--------------|-------------|-------------|----------|
  | 數字         | "3,465.00"  | "9.93"      | 3465.0   |
  | 本益比空白   | "-"         | "N/A"       | None     |
  | 財報季別     | "115/2"     | "115Q2"     | "115/Q2" |
  | 代號         | "1101"      | "1240"      | "1101"   |

兩邊都可以指定日期，所以每日排程與日後回補歷史用的是同一組函式。
欄位用名稱找，不用固定索引：交易所調整欄位順序時才不會靜靜地讀錯欄。
"""
import asyncio
import logging
import re
from datetime import date
from typing import Optional

import httpx
import pandas as pd

logger = logging.getLogger(__name__)

TWSE_URL = "https://www.twse.com.tw/rwd/zh/afterTrading/BWIBBU_d"
TPEX_URL = "https://www.tpex.org.tw/www/zh-tw/afterTrading/peQryDate"
REQUEST_TIMEOUT = 30
RETRY_COUNT = 3
RETRY_DELAY = 3     # 秒，第 n 次失敗後等 n × RETRY_DELAY

# 櫃買中心要瀏覽器 UA，否則可能被 Cloudflare 擋（與三大法人同一套做法）
_TPEX_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "application/json",
}

VALUATION_COLUMNS = [
    "code", "trade_date", "pe_ratio", "pb_ratio", "dividend_yield", "fin_period",
]

_TWSE_CODE_RE = re.compile(r"^\d{4}$")       # 與 twse_scraper 一致：上市普通股 4 碼
_TPEX_CODE_RE = re.compile(r"^\d{4,5}$")     # 與 tpex_scraper 一致：上櫃 4～5 碼

# 欄位名稱 → 統一後的鍵。兩市名稱不同的只有代號一欄。
_FIELD_KEYS = {
    "證券代號":   "code",
    "股票代號":   "code",
    "本益比":     "pe_ratio",
    "股價淨值比": "pb_ratio",
    "殖利率(%)":  "dividend_yield",
    "財報年/季":  "fin_period",
}

# 只有「財報年/季」可以缺：2024 年以前的上櫃估值表沒有這一欄（回補歷史時實測發現），
# 缺了只是少顯示一個季別標籤。其餘欄位仍然缺一不可——尤其本益比，它空白代表
# 「虧損中」，交易所若改了欄名、我們卻默默讀成空值，會變成全市場都顯示虧損中，
# 這種無聲的錯比整份拒收更糟。
_OPTIONAL_KEYS = {"fin_period"}


# ── 格式統一 ──────────────────────────────────────────────────
def to_number(v) -> Optional[float]:
    """'3,465.00' → 3465.0；'-'、'N/A'、空字串 → None"""
    try:
        return float(str(v).replace(",", "").strip())
    except (ValueError, TypeError):
        return None


def normalize_fin_period(v) -> Optional[str]:
    """'115/2'、'115Q2' → '115/Q2'；看不懂的格式回傳 None，不硬猜"""
    m = re.fullmatch(r"\s*(\d{2,3})\s*/?\s*Q?\s*([1-4])\s*", str(v or ""))
    return f"{m.group(1)}/Q{m.group(2)}" if m else None


def _column_index(fields: list[str]) -> dict[str, int]:
    """把回應的欄位名稱對到統一鍵；缺任何一欄就回空 dict，讓呼叫端放棄整份資料"""
    idx = {_FIELD_KEYS[f]: i for i, f in enumerate(fields) if f in _FIELD_KEYS}
    missing = set(_FIELD_KEYS.values()) - _OPTIONAL_KEYS - idx.keys()
    if missing:
        logger.error(f"[Valuation] 回應缺少欄位 {sorted(missing)}，實際欄位：{fields}")
        return {}
    return idx


def _rows_to_frame(rows: list, fields: list[str], target: date, code_re: re.Pattern) -> pd.DataFrame:
    idx = _column_index(fields)
    if not idx:
        return pd.DataFrame(columns=VALUATION_COLUMNS)

    records = []
    for row in rows:
        code = str(row[idx["code"]]).strip()
        if not code_re.match(code):
            continue
        pb = to_number(row[idx["pb_ratio"]])
        records.append({
            "code":           code,
            "trade_date":     target,
            "pe_ratio":       to_number(row[idx["pe_ratio"]]),
            # PB ≤ 0 沒有意義（淨值為負時交易所會留空，這裡多一道保險）
            "pb_ratio":       pb if pb and pb > 0 else None,
            "dividend_yield": to_number(row[idx["dividend_yield"]]),
            "fin_period":     (normalize_fin_period(row[idx["fin_period"]])
                               if "fin_period" in idx else None),
        })
    return pd.DataFrame(records, columns=VALUATION_COLUMNS)


# ── HTTP ──────────────────────────────────────────────────────
async def _get_json(client: httpx.AsyncClient, url: str, params: dict,
                    label: str, headers: Optional[dict] = None) -> Optional[dict]:
    """
    帶重試的 GET。實測證交所偶爾會直接斷線（錯誤訊息是空的），
    重試一兩次就會成功；三次都失敗才放棄，回傳 None。
    """
    for attempt in range(1, RETRY_COUNT + 1):
        try:
            r = await client.get(url, params=params, headers=headers, timeout=REQUEST_TIMEOUT)
            r.raise_for_status()
            return r.json()
        except (httpx.HTTPError, ValueError) as e:
            logger.warning(f"[{label}] 第 {attempt}/{RETRY_COUNT} 次失敗：{type(e).__name__} {e}")
            if attempt < RETRY_COUNT:
                await asyncio.sleep(RETRY_DELAY * attempt)
    return None


# ── 上市 ──────────────────────────────────────────────────────
def parse_twse_payload(payload: dict, target: date) -> pd.DataFrame:
    """非交易日、日期對不上、或欄位缺漏時回傳空表，不 raise"""
    if payload.get("stat") != "OK" or not payload.get("data"):
        return pd.DataFrame(columns=VALUATION_COLUMNS)
    if payload.get("date") and payload["date"] != target.strftime("%Y%m%d"):
        logger.warning(f"[TWSE] 估值表要求 {target}，回應日期為 {payload['date']}，略過")
        return pd.DataFrame(columns=VALUATION_COLUMNS)
    return _rows_to_frame(payload["data"], payload.get("fields") or [], target, _TWSE_CODE_RE)


async def fetch_twse_on(client: httpx.AsyncClient, target: date) -> pd.DataFrame:
    payload = await _get_json(
        client, TWSE_URL,
        {"date": target.strftime("%Y%m%d"), "selectType": "ALL", "response": "json"},
        label=f"TWSE 估值表 {target}",
    )
    df = parse_twse_payload(payload or {}, target)
    logger.info(f"[TWSE] 估值表：{len(df)} 筆（{target}）")
    return df


# ── 上櫃 ──────────────────────────────────────────────────────
def _roc_slash_to_date(s: str) -> Optional[date]:
    """'115/11/06' → date(2026, 11, 6)"""
    try:
        y, m, d = (int(x) for x in str(s).split("/"))
        return date(y + 1911, m, d)
    except (ValueError, TypeError):
        return None


def parse_tpex_payload(payload: dict, target: date) -> pd.DataFrame:
    """非交易日、日期對不上、或欄位缺漏時回傳空表，不 raise"""
    tables = payload.get("tables") or []
    if not tables or not tables[0].get("data"):
        return pd.DataFrame(columns=VALUATION_COLUMNS)
    table = tables[0]
    actual = _roc_slash_to_date(table.get("date"))
    if actual and actual != target:
        logger.warning(f"[TPEX] 估值表要求 {target}，回應日期為 {actual}，略過")
        return pd.DataFrame(columns=VALUATION_COLUMNS)
    return _rows_to_frame(table["data"], table.get("fields") or [], target, _TPEX_CODE_RE)


async def fetch_tpex_on(client: httpx.AsyncClient, target: date) -> pd.DataFrame:
    roc = f"{target.year - 1911}/{target.month:02d}/{target.day:02d}"
    payload = await _get_json(
        client, TPEX_URL, {"date": roc, "response": "json"},
        label=f"TPEX 估值表 {target}", headers=_TPEX_HEADERS,
    )
    df = parse_tpex_payload(payload or {}, target)
    logger.info(f"[TPEX] 估值表：{len(df)} 筆（{target}）")
    return df


# ── 每股淨值 ──────────────────────────────────────────────────
def attach_bvps(valuations: pd.DataFrame, quotes: pd.DataFrame) -> pd.DataFrame:
    """
    每股淨值 = 同一天的收盤價 ÷ PB，四捨五入到小數兩位。

    上櫃的估值表沒有收盤價，所以兩市一律用 daily_quotes 那份收盤價，
    算法只有一種。用 (code, trade_date) 對應，日期不同的不會配錯。
    """
    out = valuations.copy()
    if out.empty:
        out["bvps"] = pd.Series(dtype="float64")
        return out

    close_map = {
        (c, d): float(v)
        for c, d, v in zip(quotes["code"], quotes["trade_date"], quotes["close"])
        if v is not None and not pd.isna(v)
    }

    def _bvps(code, trade_date, pb):
        close = close_map.get((code, trade_date))
        if close is None or pb is None or pd.isna(pb) or pb <= 0:
            return None
        return round(close / pb, 2)

    out["bvps"] = [
        _bvps(c, d, pb) for c, d, pb in zip(out["code"], out["trade_date"], out["pb_ratio"])
    ]
    return out
