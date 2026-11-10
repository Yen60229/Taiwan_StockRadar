"""
兩市估值表（本益比、殖利率、股價淨值比）的解析測試。

範例檔是 2026-11-06 的真實回應（截取部分列）。重點是兩邊格式不同，
解析後必須完全一致：數字去逗號、空白一律變空值、財報季別統一成 115/Q2。
（pandas 的數字欄會把 None 存成 NaN，寫入資料庫時 _safe_float 會轉回 NULL。）
"""
from datetime import date

import pandas as pd
import pytest

from scraper.valuation import (
    VALUATION_COLUMNS,
    attach_bvps,
    normalize_fin_period,
    parse_tpex_payload,
    parse_twse_payload,
    to_number,
)

DAY = date(2026, 11, 6)


def _row(df: pd.DataFrame, code: str) -> dict:
    return df[df["code"] == code].iloc[0].to_dict()


# ── 格式統一 ──────────────────────────────────────────────────
@pytest.mark.parametrize("raw, expected", [
    ("115/2", "115/Q2"),     # 上市
    ("115Q3", "115/Q3"),     # 上櫃
    ("115/Q4", "115/Q4"),
    (" 99/1 ", "99/Q1"),
    ("", None),
    (None, None),
    ("115/5", None),         # 沒有第 5 季
    ("abc", None),
])
def test_normalize_fin_period(raw, expected):
    assert normalize_fin_period(raw) == expected


@pytest.mark.parametrize("raw, expected", [
    ("3,465.00", 3465.0),
    ("0.87", 0.87),
    ("-", None),
    ("N/A", None),
    ("", None),
    (None, None),
])
def test_to_number(raw, expected):
    assert to_number(raw) == expected


# ── 上市 ──────────────────────────────────────────────────────
def test_twse_parses_real_payload(fx):
    df = parse_twse_payload(fx.json("twse_bwibbu_20261106.json"), DAY)

    assert list(df.columns) == VALUATION_COLUMNS
    assert len(df) == 18
    assert (df["trade_date"] == DAY).all()

    tsmc = _row(df, "2330")
    assert tsmc["pe_ratio"] == pytest.approx(24.75)
    assert tsmc["pb_ratio"] == pytest.approx(8.61)
    assert tsmc["dividend_yield"] == pytest.approx(1.03)
    assert tsmc["fin_period"] == "115/Q2"


def test_twse_loss_and_thousands(fx):
    df = parse_twse_payload(fx.json("twse_bwibbu_20261106.json"), DAY)
    assert pd.isna(_row(df, "1101")["pe_ratio"])                   # 台泥 "-" → 虧損
    assert _row(df, "1436")["pe_ratio"] == pytest.approx(3465.0)   # "3,465.00"
    assert _row(df, "1436")["fin_period"] == "115/Q3"


def test_twse_rejects_other_date(fx):
    """要求的日期與回應不同（例如當天還沒公布）時不能寫錯日期"""
    assert parse_twse_payload(fx.json("twse_bwibbu_20261106.json"), date(2026, 11, 7)).empty


@pytest.mark.parametrize("payload", [
    {},
    {"stat": "很抱歉，沒有符合條件的資料!"},
    {"stat": "OK", "data": []},
])
def test_twse_empty_on_non_trading_day(payload):
    assert parse_twse_payload(payload, DAY).empty


def test_twse_missing_field_returns_empty(fx):
    """欄位改名時寧可整份不收，也不要讀錯欄"""
    payload = fx.json("twse_bwibbu_20261106.json")
    payload["fields"] = [f.replace("股價淨值比", "淨值比") for f in payload["fields"]]
    assert parse_twse_payload(payload, DAY).empty


def test_tpex_old_payload_without_fin_period_still_parses(fx):
    """
    回歸測試（第二階段回補歷史時實測發現）：2024 年以前的上櫃估值表沒有
    「財報年/季」欄。舊版規定六欄缺一不可，整份被當成壞資料丟掉，
    上櫃的歷史 PB 一筆都收不進來。只有季別可以缺（缺了只是少一個標籤）；
    代號和 PB 仍然必備，見 test_tpex_missing_pb_returns_empty。
    """
    payload = fx.json("tpex_pe_20261106.json")
    table = payload["tables"][0]
    drop = table["fields"].index("財報年/季")
    table["fields"] = [f for i, f in enumerate(table["fields"]) if i != drop]
    table["data"] = [[v for i, v in enumerate(row) if i != drop] for row in table["data"]]

    df = parse_tpex_payload(payload, DAY)

    assert len(df) == 15
    assert df["fin_period"].isna().all()
    assert _row(df, "1240")["pb_ratio"] == pytest.approx(1.57)


def test_tpex_missing_pb_returns_empty(fx):
    """PB 欄被改名時仍然整份不收：不能默默把每一檔讀成沒有 PB"""
    payload = fx.json("tpex_pe_20261106.json")
    table = payload["tables"][0]
    table["fields"] = [f.replace("股價淨值比", "淨值比") for f in table["fields"]]
    assert parse_tpex_payload(payload, DAY).empty


def test_missing_pe_still_rejects_the_whole_payload(fx):
    """
    本益比不能比照季別放寬：本益比空白就是「虧損中」標籤的依據，
    交易所改欄名時若默默讀成空值，會變成全市場都顯示虧損中。
    """
    payload = fx.json("twse_bwibbu_20261106.json")
    payload["fields"] = [f.replace("本益比", "PE") for f in payload["fields"]]
    assert parse_twse_payload(payload, DAY).empty


# ── 上櫃 ──────────────────────────────────────────────────────
def test_tpex_parses_real_payload(fx):
    df = parse_tpex_payload(fx.json("tpex_pe_20261106.json"), DAY)

    assert list(df.columns) == VALUATION_COLUMNS
    assert len(df) == 15

    first = _row(df, "1240")
    assert first["pe_ratio"] == pytest.approx(9.93)
    assert first["pb_ratio"] == pytest.approx(1.57)
    assert first["dividend_yield"] == pytest.approx(0.94)
    assert first["fin_period"] == "115/Q2"


def test_tpex_loss_and_q3(fx):
    df = parse_tpex_payload(fx.json("tpex_pe_20261106.json"), DAY)
    assert pd.isna(_row(df, "1569")["pe_ratio"])         # "N/A" → 虧損
    assert _row(df, "1268")["fin_period"] == "115/Q3"    # "115Q3"


def test_tpex_rejects_other_date(fx):
    assert parse_tpex_payload(fx.json("tpex_pe_20261106.json"), date(2026, 11, 7)).empty


def test_both_markets_produce_identical_types(fx):
    """兩市解析後每一欄的型別必須相同，下游才不用分開處理"""
    twse = parse_twse_payload(fx.json("twse_bwibbu_20261106.json"), DAY)
    tpex = parse_tpex_payload(fx.json("tpex_pe_20261106.json"), DAY)
    for col in VALUATION_COLUMNS:
        t_types = {type(v) for v in twse[col] if v is not None and not pd.isna(v)}
        p_types = {type(v) for v in tpex[col] if v is not None and not pd.isna(v)}
        assert t_types == p_types, f"{col}: 上市 {t_types} / 上櫃 {p_types}"
    assert twse["fin_period"].str.fullmatch(r"\d{3}/Q[1-4]").all()
    assert tpex["fin_period"].str.fullmatch(r"\d{3}/Q[1-4]").all()


# ── 每股淨值 ──────────────────────────────────────────────────
def test_attach_bvps_uses_same_day_close():
    vals = pd.DataFrame([
        {"code": "2330", "trade_date": DAY, "pe_ratio": 24.75, "pb_ratio": 8.61,
         "dividend_yield": 1.03, "fin_period": "115/Q2"},
        {"code": "9999", "trade_date": DAY, "pe_ratio": None, "pb_ratio": None,
         "dividend_yield": None, "fin_period": None},
        {"code": "1240", "trade_date": DAY, "pe_ratio": 9.93, "pb_ratio": 1.57,
         "dividend_yield": 0.94, "fin_period": "115/Q2"},
    ])
    quotes = pd.DataFrame([
        {"code": "2330", "trade_date": DAY, "close": 2135.0},
        {"code": "9999", "trade_date": DAY, "close": 10.0},
        # 1240 只有前一天的收盤價 → 日期對不上，不能拿來算
        {"code": "1240", "trade_date": date(2026, 11, 5), "close": 60.0},
    ])
    out = attach_bvps(vals, quotes).set_index("code")["bvps"]

    assert out["2330"] == pytest.approx(round(2135.0 / 8.61, 2))
    assert pd.isna(out["9999"])     # PB 空白
    assert pd.isna(out["1240"])     # 沒有同一天的收盤價


def test_attach_bvps_empty():
    out = attach_bvps(pd.DataFrame(columns=VALUATION_COLUMNS), pd.DataFrame())
    assert out.empty and "bvps" in out.columns
