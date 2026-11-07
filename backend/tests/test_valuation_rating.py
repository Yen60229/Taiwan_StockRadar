"""股價淨值比評級規則的邊界測試（不需要資料庫）"""
import pytest

from api.valuation import (
    CHEAP_PCT, EXPENSIVE_PCT, MIN_INDUSTRY_N,
    RATING_CHEAP, RATING_EXPENSIVE, RATING_FAIR, rate_pb,
)


@pytest.mark.parametrize("pct, expected", [
    (0.0,           RATING_CHEAP),
    (CHEAP_PCT,     RATING_CHEAP),       # 剛好 25% 算便宜
    (0.2501,        RATING_FAIR),
    (0.5,           RATING_FAIR),
    (0.7499,        RATING_FAIR),
    (EXPENSIVE_PCT, RATING_EXPENSIVE),   # 剛好 75% 算昂貴
    (1.0,           RATING_EXPENSIVE),
])
def test_rating_by_industry_percentile(pct, expected):
    assert rate_pb(1.5, pct, MIN_INDUSTRY_N) == expected


def test_small_industry_not_rated():
    """同產業不到 10 檔不評級，也不改用 PB < 1 這種絕對門檻"""
    assert rate_pb(0.5, 0.0, MIN_INDUSTRY_N - 1) is None
    assert rate_pb(0.5, 0.0, MIN_INDUSTRY_N) == RATING_CHEAP


@pytest.mark.parametrize("pb, pct, n", [
    (None, 0.1, 50),     # 淨值為負，交易所留空
    (1.2, None, 50),
    (1.2, 0.1, None),    # 沒有產業別
])
def test_missing_data_not_rated(pb, pct, n):
    assert rate_pb(pb, pct, n) is None
