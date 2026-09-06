"""
ISIN 網站（isin.twse.com.tw/isin/C_public.jsp）HTML 解析。

TWSE（strMode=2）與 TPEX（strMode=4）的公司基本資料都來自這個網站，
除了代號位數不同之外解析邏輯完全一樣，因此抽成共用的純函式。

抽出來的另一個理由：這個網站的 HTML 結構變動過多次
（欄位數從 6 變 7 就讓 TPEX 產業一度全部變成「其他」），
是整個專案最值得寫回歸測試的地方——純函式才測得動。
"""
import logging
import re

import pandas as pd
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

COLUMNS = ["code", "name", "short_name", "industry"]

# 資料列共 7 格：有價證券代號及名稱 | ISIN | 上市日 | 市場別 | 產業別 | CFICode | 備註
ROW_CELL_COUNT = 7
CODE_NAME_COL  = 0
INDUSTRY_COL   = 4

# 代號與名稱之間是全形空格 U+3000，不是半形空白
FULLWIDTH_SPACE = "　"


def empty_frame() -> pd.DataFrame:
    """欄位齊全的空 DataFrame，讓呼叫端不必特別處理 None"""
    return pd.DataFrame(columns=COLUMNS)


def parse_isin_html(html: str, code_pattern: str) -> pd.DataFrame:
    """
    解析 ISIN 頁面 HTML，回傳 code / name / short_name / industry。

    code_pattern：只保留符合此正則的代號
        TWSE 上市普通股 → r"^\\d{4}$"
        TPEX 上櫃普通股 → r"^\\d{4,5}$"
    （用來排除權證、ETF、特別股等非普通股）

    ISIN 的「名稱」本身就是市場簡稱（台積電、台塑化），
    所以 name 與 short_name 相同。
    """
    soup = BeautifulSoup(html, "html.parser")
    code_re = re.compile(code_pattern)

    records = []
    for row in soup.find_all("tr"):
        cells = [td.get_text(strip=True) for td in row.find_all("td")]
        if len(cells) != ROW_CELL_COUNT:
            continue

        raw = cells[CODE_NAME_COL]
        if FULLWIDTH_SPACE not in raw:
            continue          # 標題列與分類列沒有「代號　名稱」格式
        code, _, name = raw.partition(FULLWIDTH_SPACE)
        code, name = code.strip(), name.strip()
        if not code_re.match(code):
            continue

        records.append({
            "code":       code,
            "name":       name,
            "short_name": name,
            "industry":   cells[INDUSTRY_COL].strip() or "其他",
        })

    if not records:
        return empty_frame()
    return pd.DataFrame(records)[COLUMNS]
