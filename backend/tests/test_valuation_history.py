"""
第二階段：跟自己的歷史比（需要 PostgreSQL 的部分同 test_db_smoke.py）。

情境（最新資料日 2026-11-06）：
  2330：2022-11 ～ 2026-10 共 48 個月，PB 依序 0.1、0.2 … 4.8
        本月（11 月）有兩筆：11/02 PB 9.9、11/06 PB 1.0（最新）
        2021-10 有一筆 PB 0.01：超過 5 年，不能算進去
  1101：只有 20 個月歷史 → 有百分位，但不評級
"""
from datetime import date
from decimal import Decimal

import pytest

from api.deps import create_access_token, hash_password
from api.valuation import (
    CHEAP_PCT, EXPENSIVE_PCT, MIN_HIST_MONTHS,
    RATING_CHEAP, RATING_EXPENSIVE, RATING_FAIR, rate_history,
)
from sqlalchemy import func, select

from models.database import ROLE_USER, STATUS_ACTIVE, Stock, User, ValuationMonthly
from pipeline.data_pipeline import upsert_valuations
from scripts.backfill_valuation import month_ends, weekdays_backwards

DAY = date(2026, 11, 6)


# ── 評級規則（不需要資料庫）────────────────────────────────────
@pytest.mark.parametrize("pct, expected", [
    (0.0,           RATING_CHEAP),
    (CHEAP_PCT,     RATING_CHEAP),
    (0.5,           RATING_FAIR),
    (EXPENSIVE_PCT, RATING_EXPENSIVE),
    (1.0,           RATING_EXPENSIVE),
])
def test_rate_history(pct, expected):
    assert rate_history(pct, MIN_HIST_MONTHS) == expected


def test_rate_history_needs_three_years():
    assert rate_history(0.0, MIN_HIST_MONTHS - 1) is None
    assert rate_history(None, 60) is None


# ── 回補腳本的日期邏輯（不需要資料庫）──────────────────────────
def test_month_ends_starts_from_last_month():
    ends = month_ends(date(2026, 11, 10), 1)
    assert len(ends) == 12
    assert ends[0] == date(2025, 11, 30)
    assert ends[-1] == date(2026, 10, 31)       # 本月不回補，交給每日排程
    assert date(2026, 2, 28) in ends


def test_weekdays_backwards_skips_weekends_and_stays_in_month():
    # 2026-05-31 是星期日
    days = list(weekdays_backwards(date(2026, 5, 31)))
    assert days[0] == date(2026, 5, 29)         # 星期五
    assert all(d.weekday() < 5 for d in days)
    assert all(d.month == 5 for d in days)


# ── 資料庫 ────────────────────────────────────────────────────
def _month_end(year: int, month: int) -> date:
    """該月 28 日（每月都有，當成那個月的樣本日）"""
    return date(year, month, 28)


def _row(code, d, pb, bvps=None, pe=None):
    return {"code": code, "trade_date": d, "pb_ratio": pb, "bvps": bvps,
            "pe_ratio": pe, "dividend_yield": None, "fin_period": None}


@pytest.fixture
async def auth(db_session):
    """透過 upsert_valuations 寫入，跟正式流程一樣會同時更新每月快照"""
    user = User(email="hist@example.com", hashed_pw=await hash_password("hist-test-password"),
                role=ROLE_USER, status=STATUS_ACTIVE)
    db_session.add_all([
        user,
        Stock(code="2330", name="台積電", short_name="台積電", market="TWSE", industry="半導體業"),
        Stock(code="1101", name="台泥", short_name="台泥", market="TWSE", industry="水泥工業"),
    ])
    await db_session.commit()
    await db_session.refresh(user)

    rows = []
    y, m = 2022, 11
    for i in range(1, 49):                                   # 48 個月：PB 0.1 ～ 4.8
        rows.append(_row("2330", _month_end(y, m), i / 10))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    rows += [
        _row("2330", date(2021, 10, 29), 0.01),              # 超過 5 年
        # 本月：故意先寫較新的 11/06，再寫較舊的 11/02，快照要留 11/06
        _row("2330", DAY, 1.0, bvps=100.0, pe=20.0),
        _row("2330", date(2026, 11, 2), 9.9),
    ]
    y, m = 2024, 11
    for _ in range(20):                                      # 1101：只有 20 個月
        rows.append(_row("1101", _month_end(y, m), 1.5))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    rows.append(_row("1101", DAY, 0.5, bvps=50.0, pe=10.0))

    await upsert_valuations(db_session, rows)
    return {"Authorization": f"Bearer {create_access_token(user.id, user.email)}"}


async def test_monthly_snapshot_keeps_latest_day(db_session, auth):
    """同一個月寫入多天，快照只留最新一天；較舊的日期晚寫入也不會蓋掉"""
    snap = (await db_session.execute(
        select(ValuationMonthly).where(ValuationMonthly.stock_code == "2330",
                                       ValuationMonthly.month == date(2026, 11, 1))
    )).scalar_one()
    assert snap.trade_date == DAY
    assert snap.pb_ratio == Decimal("1.00")

    count = (await db_session.execute(
        select(func.count()).select_from(ValuationMonthly).where(ValuationMonthly.stock_code == "2330")
    )).scalar_one()
    assert count == 50                                       # 48 個月 + 5 年前那筆 + 本月


async def test_stock_detail_history_fields(db_client, auth):
    r = await db_client.get("/api/stocks/2330", headers=auth)
    assert r.status_code == 200
    b = r.json()

    assert b["history_n"] == 48                     # 不含本月、不含 5 年前
    assert b["history_since"] == "2022-11-28"
    # 目前 PB 1.0：比它低的 9 個月、相等 1 個月 → (9 + 0.5) / 48
    assert b["history_pb_pct"] == pytest.approx(9.5 / 48, abs=1e-4)
    assert b["history_rating"] == "cheap"
    assert b["history_pb_p50"] == pytest.approx(2.45, abs=0.01)
    assert b["history_pb_p25"] == pytest.approx(1.275, abs=0.01)
    # 參考價位 = 每股淨值 100 × 歷史百分位
    assert b["price_fair"] == pytest.approx(245.0, abs=1)
    assert b["price_cheap"] < b["price_fair"] < b["price_expensive"]


async def test_short_history_not_rated(db_client, auth):
    b = (await db_client.get("/api/stocks/1101", headers=auth)).json()
    assert b["history_n"] == 20
    assert b["history_pb_pct"] == 0.0               # 0.5 比過去 20 個月的 1.5 都低
    assert b["history_rating"] is None              # 不到 36 個月不評級
    assert b["price_cheap"] is None                 # 參考價位也不給
    assert b["pb_rating"] is None                   # 同產業只有 1 檔，也不評級


async def test_history_series(db_client, auth):
    r = await db_client.get("/api/valuation/history/2330", headers=auth)
    assert r.status_code == 200
    b = r.json()

    dates = [p["date"] for p in b["points"]]
    assert dates[0] == "2022-11-28"                 # 5 年前的那筆不出現
    assert dates[-1] == "2026-11-06"                # 本月只取最新一天
    assert "2026-11-02" not in dates
    assert len(dates) == 49
    assert b["points"][-1]["pb"] == 1.0
    assert b["n"] == 48
    assert b["p50"] == pytest.approx(2.45, abs=0.01)


async def test_history_series_unknown_stock(db_client, auth):
    b = (await db_client.get("/api/valuation/history/9999", headers=auth)).json()
    assert b == {"code": "9999", "points": [], "p25": None, "p50": None, "p75": None, "n": 0}


async def test_industry_endpoint_includes_history(db_client, auth):
    b = (await db_client.get("/api/valuation/industry",
                             params={"industry": "半導體業"}, headers=auth)).json()
    item = b["items"][0]
    assert item["code"] == "2330"
    assert item["history_rating"] == "cheap"
