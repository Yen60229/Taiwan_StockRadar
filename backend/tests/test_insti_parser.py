"""
三大法人買賣超解析的回歸測試。

兩個來源的欄位都是「靠索引取值」，沒有名稱可依靠：
  TWSE T86        → row[4] 外資 / row[10] 投信 / row[11] 自營 / row[18] 合計
  TPEX dailyTrade → row[10] 外資 / row[13] 投信 / row[22] 自營 / row[23] 合計
只要對方調整欄位順序，資料就會靜靜地全部錯掉而不報錯——所以要用真實樣本鎖住。
"""
from datetime import date

import pytest

from scraper.tpex_scraper import parse_insti_payload
from scraper.twse_scraper import _parse_t86_payload

TRADE_DAY = date(2026, 9, 4)


# ── TWSE T86 ──────────────────────────────────────────────────
def test_t86_parses_real_payload(fx):
    df = _parse_t86_payload(fx.json("t86_20260904.json"), TRADE_DAY)

    assert list(df.columns) == [
        "code", "trade_date", "foreign_net", "trust_net", "dealer_net", "total_net"
    ]
    assert (df["trade_date"] == TRADE_DAY).all()
    assert "2324" in df["code"].tolist()


def test_t86_converts_shares_to_lots(fx):
    """T86 給的是股數，DB 存的是張數（÷1000）"""
    df = _parse_t86_payload(fx.json("t86_20260904.json"), TRADE_DAY)
    compal = df[df["code"] == "2324"].iloc[0]

    assert compal["foreign_net"] == pytest.approx(69_366_284 / 1000)
    assert compal["trust_net"] == pytest.approx(-21_000 / 1000)
    assert compal["dealer_net"] == pytest.approx(1_671_047 / 1000)
    assert compal["total_net"] == pytest.approx(71_016_331 / 1000)


def test_t86_filters_non_four_digit_codes(fx):
    """00685L 這類槓桿 ETF / 權證代號不是 4 碼普通股，要排除"""
    df = _parse_t86_payload(fx.json("t86_20260904.json"), TRADE_DAY)
    assert "00685L" not in df["code"].tolist()
    assert df["code"].str.fullmatch(r"\d{4}").all()


@pytest.mark.parametrize("payload", [
    {},
    {"stat": "很抱歉，沒有符合條件的資料！"},
    {"stat": "OK", "data": []},
    {"stat": "OK"},
])
def test_t86_returns_empty_on_non_trading_day(payload):
    """非交易日回空表，不能 raise、也不能回半套資料"""
    assert _parse_t86_payload(payload, TRADE_DAY).empty


# ── TPEX dailyTrade ───────────────────────────────────────────
def test_tpex_insti_parses_real_payload(fx):
    df = parse_insti_payload(fx.json("tpex_insti_20260904.json"), TRADE_DAY)

    assert not df.empty
    assert (df["trade_date"] == TRADE_DAY).all()
    assert "00858" in df["code"].tolist()


def test_tpex_insti_column_indices_are_self_consistent(fx):
    """
    TPEX 那 24 欄沒有官方文件，欄位索引是用算術驗出來的：
    外資[10] + 投信[13] + 自營[22] 必須等於三大法人合計[23]。
    這條斷言就是索引正確性的證明——改版錯位時會立刻紅燈。
    """
    df = parse_insti_payload(fx.json("tpex_insti_20260904.json"), TRADE_DAY)

    for _, r in df.iterrows():
        parts = r["foreign_net"] + r["trust_net"] + r["dealer_net"]
        assert parts == pytest.approx(r["total_net"], abs=1e-6), \
            f"{r['code']} 三者相加 {parts} != 合計 {r['total_net']}"


def test_tpex_insti_filters_non_numeric_codes(fx):
    """00411A（主動式 ETF）含字母，不是普通股代號"""
    df = parse_insti_payload(fx.json("tpex_insti_20260904.json"), TRADE_DAY)
    assert "00411A" not in df["code"].tolist()
    assert df["code"].str.fullmatch(r"\d{4,5}").all()


def test_tpex_insti_rejects_date_mismatch(fx):
    """
    要求 9/5 卻拿到 9/4 的資料時必須回空表。
    否則會把週五的資料標成週六寫進 DB —— 就是 P0-2 的另一個入口。
    """
    df = parse_insti_payload(fx.json("tpex_insti_20260904.json"), date(2026, 9, 5))
    assert df.empty


@pytest.mark.parametrize("payload", [
    {},
    {"tables": []},
    {"tables": [{"date": "115/09/04", "data": []}]},
])
def test_tpex_insti_returns_empty_on_non_trading_day(payload):
    assert parse_insti_payload(payload, TRADE_DAY).empty
