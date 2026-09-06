"""
交易日解析的回歸測試（P0-2）。

原本的 bug：行情寫入時一律用 date.today()。週末或假日跑排程時，
抓到的是上一個交易日的資料，卻被標上「今天」的日期寫進時序表——
`daily_quotes` 因此出現週六/週日的列，20 日均量也被污染。

修法的核心原則：**日期一律取自 API payload，取不到就失敗，絕不 fallback 到今天。**
"""
from datetime import date, datetime

import pandas as pd
import pytest

from pipeline.data_pipeline import _row_trade_date
from scraper import tpex_scraper as tp
from scraper import twse_scraper as tw


# ── 民國日期解析 ──────────────────────────────────────────────
@pytest.mark.parametrize("roc,expected", [
    ("1150904", date(2026, 9, 4)),
    ("1150101", date(2026, 1, 1)),
    ("1151231", date(2026, 12, 31)),
    ("0990105", date(2010, 1, 5)),
])
def test_twse_roc_to_date(roc, expected):
    assert tw._roc_to_date(roc) == expected


def test_twse_roc_to_date_returns_none_on_garbage():
    for bad in ["", "abc", None, "12"]:
        assert tw._roc_to_date(bad) is None


def test_tpex_roc_to_date_raises_instead_of_returning_today():
    """
    回歸測試：舊版解析失敗時 `return date.today()`，等於把壞資料標成今天。
    現在必須 raise，讓 pipeline 直接失敗而不是靜靜寫入錯誤日期。
    """
    assert tp._roc_to_date("1150904") == date(2026, 9, 4)
    for bad in ["", "abc", None]:
        with pytest.raises(ValueError):
            tp._roc_to_date(bad)


# ── 從 payload 取交易日 ───────────────────────────────────────
def test_payload_trade_date_from_real_quotes(fx):
    """用真實的 STOCK_DAY_ALL 樣本：Date=1150904 應解析成 2026-09-04（週五）"""
    df = pd.DataFrame(fx.json("twse_quotes.json"))
    assert tw._payload_trade_date(df, "TWSE") == date(2026, 9, 4)


def test_payload_trade_date_raises_when_date_missing():
    """缺 Date 欄時必須 raise —— 這是 P0-2 的核心：寧可失敗也不寫今天的日期"""
    with pytest.raises(ValueError, match="拒絕以今日日期寫入"):
        tw._payload_trade_date(pd.DataFrame([{"Code": "2330", "ClosingPrice": "1000"}]), "TWSE")


def test_payload_trade_date_raises_on_empty_frame():
    with pytest.raises(ValueError):
        tw._payload_trade_date(pd.DataFrame(), "TWSE")


def test_payload_trade_date_raises_on_unparsable_date():
    with pytest.raises(ValueError):
        tw._payload_trade_date(pd.DataFrame([{"Date": "not-a-date"}]), "TWSE")


def test_payload_trade_date_never_returns_today_for_bad_input():
    """把「絕不 fallback 到今天」這件事直接寫成斷言"""
    for bad in [pd.DataFrame(), pd.DataFrame([{"Date": ""}]), pd.DataFrame([{"X": 1}])]:
        try:
            got = tw._payload_trade_date(bad, "TWSE")
        except ValueError:
            continue
        pytest.fail(f"應該 raise，卻回傳了 {got}（今天是 {date.today()}）")


# ── upsert 時逐列取日期 ───────────────────────────────────────
def test_row_trade_date_prefers_row_value():
    """
    回歸測試：舊版 upsert_daily_quotes 收到 df 之後，仍用 date.today() 蓋掉
    scraper 已經算好的 trade_date——只改 scraper 是修不好的。
    """
    row = {"code": "2330", "trade_date": date(2026, 9, 4)}
    assert _row_trade_date(row, date(2026, 9, 7)) == date(2026, 9, 4)


def test_row_trade_date_accepts_pandas_timestamp():
    row = {"code": "2330", "trade_date": pd.Timestamp("2026-09-04")}
    assert _row_trade_date(row, None) == date(2026, 9, 4)


def test_row_trade_date_accepts_datetime():
    row = {"code": "2330", "trade_date": datetime(2026, 9, 4, 13, 30)}
    assert _row_trade_date(row, None) == date(2026, 9, 4)


def test_row_trade_date_uses_fallback_when_missing():
    assert _row_trade_date({"code": "2330"}, date(2026, 9, 4)) == date(2026, 9, 4)
    assert _row_trade_date({"code": "2330", "trade_date": None}, date(2026, 9, 4)) == date(2026, 9, 4)


def test_row_trade_date_raises_when_nothing_available():
    """既沒有列上的日期、呼叫端也沒指定 → 失敗，不要猜"""
    with pytest.raises(ValueError):
        _row_trade_date({"code": "2330"}, None)
