"""
交易日盤後 pipeline 的回歸測試。

生產環境實際踩到的 bug：TWSE 與 TPEX 當天回報的交易日不一致
（TWSE 尚未更新仍是前一交易日，TPEX 已經是最新一天）時，
daily_quotes 會同時寫入兩個不同的 trade_date，但均量重算只做了其中一個
（trade_date = twse_date or tpex_date 只挑一個），較新那批的 avg_vol_20d
永遠是 NULL，導致 /api/screen 全部被 WHERE avg_vol_20d >= 0 篩掉，
即使 min_avg_vol=0 也一樣（NULL >= 0 在 SQL 裡不成立）。
"""
from datetime import date

from pipeline.data_pipeline import _distinct_trade_dates


def test_two_markets_same_date_yields_single_date():
    assert _distinct_trade_dates(date(2026, 9, 4), date(2026, 9, 4)) == [date(2026, 9, 4)]


def test_two_markets_different_dates_both_kept():
    """
    回歸測試：這就是生產環境實際發生的情況（TWSE 09-07 / TPEX 09-08）。
    兩個日期都要出現，才能確保兩批都會被重算均量。
    """
    result = _distinct_trade_dates(date(2026, 9, 7), date(2026, 9, 8))
    assert result == [date(2026, 9, 7), date(2026, 9, 8)]


def test_one_market_empty():
    assert _distinct_trade_dates(date(2026, 9, 4), None) == [date(2026, 9, 4)]
    assert _distinct_trade_dates(None, date(2026, 9, 4)) == [date(2026, 9, 4)]


def test_both_empty_returns_empty_list():
    """兩市場皆無資料時（例如市場全休）不該產生任何日期去重算均量"""
    assert _distinct_trade_dates(None, None) == []


def test_result_is_sorted():
    assert _distinct_trade_dates(date(2026, 9, 8), date(2026, 9, 7)) == [
        date(2026, 9, 7), date(2026, 9, 8)
    ]
