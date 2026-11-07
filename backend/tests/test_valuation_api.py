"""
股價淨值比評級的端點測試（需要 PostgreSQL，同 test_db_smoke.py）。

情境：
  半導體業 12 檔：PB 1.0 ～ 12.0，另有 1 檔 PB 空白（淨值為負）
  塑膠工業 3 檔：不到 10 檔，不評級
  1 檔估值資料是 30 天前的（已下市），不能拿來排名
"""
from datetime import date, timedelta
from decimal import Decimal

import pytest

from api.deps import create_access_token, hash_password
from models.database import (
    ROLE_USER, STATUS_ACTIVE, ChipConcentration, DailyQuote, Stock, User, Valuation,
)
from pipeline.data_pipeline import upsert_valuations

DAY = date(2026, 11, 6)
SEMI = "半導體業"
PLASTIC = "塑膠工業"


async def _seed(db_session) -> dict:
    user = User(email="pb@example.com", hashed_pw=await hash_password("pb-test-password"),
                role=ROLE_USER, status=STATUS_ACTIVE)
    rows = [user]

    def stock(code, industry, pb, pe=Decimal("15.00"), day=DAY):
        close = Decimal("100.00")
        rows.extend([
            Stock(code=code, name=f"公司{code}", short_name=f"簡{code}",
                  market="TWSE", industry=industry),
            DailyQuote(stock_code=code, trade_date=day, close=close,
                       volume=5000, avg_vol_20d=Decimal("5000.0")),
            ChipConcentration(stock_code=code, week_date=day, conc_ratio=Decimal("50.00")),
            Valuation(stock_code=code, trade_date=day, pe_ratio=pe, pb_ratio=pb,
                      dividend_yield=Decimal("2.00"), fin_period="115/Q2",
                      bvps=(close / pb).quantize(Decimal("0.01")) if pb else None),
        ])

    for i in range(1, 13):                       # 3001 ～ 3012：PB 1 ～ 12
        stock(f"30{i:02d}", SEMI, Decimal(i))
    stock("3099", SEMI, None, pe=None)           # 淨值為負
    for i, pb in enumerate(["0.70", "0.80", "0.90"], start=1):
        stock(f"130{i}", PLASTIC, Decimal(pb))
    stock("3098", SEMI, Decimal("0.10"), day=DAY - timedelta(days=30))  # 過期資料

    db_session.add_all(rows)
    await db_session.commit()
    await db_session.refresh(user)
    return {"Authorization": f"Bearer {create_access_token(user.id, user.email)}"}


@pytest.fixture
async def auth(db_session):
    return await _seed(db_session)


async def test_screen_includes_pb_rating(db_client, auth):
    r = await db_client.get("/api/screen", params={"min_avg_vol": 0, "min_conc": 0}, headers=auth)
    assert r.status_code == 200
    items = {i["code"]: i for i in r.json()["items"]}

    # 12 檔排名：percent_rank = (名次 - 1) / 11
    assert items["3001"]["pb_rating"] == "cheap"       # 0.00
    assert items["3003"]["pb_rating"] == "cheap"       # 0.18
    assert items["3004"]["pb_rating"] == "fair"        # 0.27
    assert items["3009"]["pb_rating"] == "fair"        # 0.73
    assert items["3010"]["pb_rating"] == "expensive"   # 0.82
    assert items["3012"]["pb_rating"] == "expensive"   # 1.00

    tsmc = items["3001"]
    assert float(tsmc["pb_ratio"]) == 1.0
    assert float(tsmc["bvps"]) == 100.0
    assert tsmc["fin_period"] == "115/Q2"
    assert tsmc["industry_n"] == 12                    # 不含 PB 空白與過期的那兩檔
    assert tsmc["industry_pb_median"] == 6.5


async def test_screen_unrated_cases(db_client, auth):
    r = await db_client.get("/api/screen", params={"min_avg_vol": 0, "min_conc": 0}, headers=auth)
    items = {i["code"]: i for i in r.json()["items"]}

    negative = items["3099"]
    assert negative["pb_ratio"] is None and negative["pb_rating"] is None
    assert negative["industry_pb_pct"] is None

    small = items["1301"]                              # 塑膠只有 3 檔
    assert float(small["pb_ratio"]) == 0.7
    assert small["pb_rating"] is None

    stale = items["3098"]                              # 30 天前的估值不採用
    assert stale["pb_ratio"] is None


async def test_industry_endpoint(db_client, auth):
    r = await db_client.get("/api/valuation/industry", params={"industry": SEMI}, headers=auth)
    assert r.status_code == 200
    body = r.json()

    assert body["n"] == 12
    assert body["median"] == 6.5
    assert body["min"] == 1.0 and body["max"] == 12.0

    codes = [i["code"] for i in body["items"]]
    assert codes[:3] == ["3001", "3002", "3003"]       # PB 由低到高
    assert codes[-1] == "3099"                         # PB 空白排最後
    assert "3098" not in codes                         # 過期資料不出現
    assert float(body["items"][0]["close"]) == 100.0
    assert body["items"][0]["short_name"] == "簡3001"


async def test_industry_endpoint_unknown_industry(db_client, auth):
    r = await db_client.get("/api/valuation/industry", params={"industry": "不存在"}, headers=auth)
    assert r.status_code == 200
    assert r.json() == {"industry": "不存在", "n": 0, "median": None,
                        "min": None, "max": None, "items": []}


async def test_industry_endpoint_requires_login(db_client):
    r = await db_client.get("/api/valuation/industry", params={"industry": SEMI})
    assert r.status_code == 401


async def test_stock_detail_includes_pb(db_client, auth):
    r = await db_client.get("/api/stocks/3012", headers=auth)
    assert r.status_code == 200
    body = r.json()
    assert float(body["pb_ratio"]) == 12.0
    assert body["pb_rating"] == "expensive"


async def test_screen_without_any_valuation(db_client, db_session):
    """還沒抓過估值表時，篩選照常運作，評價欄位空白"""
    user = User(email="nov@example.com", hashed_pw=await hash_password("pb-test-password"),
                role=ROLE_USER, status=STATUS_ACTIVE)
    db_session.add_all([
        user,
        Stock(code="2330", name="台積電", market="TWSE", industry=SEMI),
        DailyQuote(stock_code="2330", trade_date=DAY, close=Decimal("1000"),
                   volume=1, avg_vol_20d=Decimal("1")),
        ChipConcentration(stock_code="2330", week_date=DAY, conc_ratio=Decimal("50")),
    ])
    await db_session.commit()
    await db_session.refresh(user)
    headers = {"Authorization": f"Bearer {create_access_token(user.id, user.email)}"}

    r = await db_client.get("/api/screen", params={"min_avg_vol": 0, "min_conc": 0}, headers=headers)
    assert r.status_code == 200
    item = r.json()["items"][0]
    assert item["pb_ratio"] is None and item["pb_rating"] is None


async def test_upsert_valuations_is_idempotent(db_session):
    row = {"code": "2330", "trade_date": DAY, "pe_ratio": 24.75, "pb_ratio": 8.61,
           "dividend_yield": 1.03, "bvps": 247.97, "fin_period": "115/Q2"}
    assert await upsert_valuations(db_session, [row]) == 1
    assert await upsert_valuations(db_session, [{**row, "pb_ratio": 8.7, "bvps": float("nan")}]) == 1

    v = (await db_session.execute(
        Valuation.__table__.select().where(Valuation.stock_code == "2330")
    )).all()
    assert len(v) == 1
    assert v[0].pb_ratio == Decimal("8.70")
    assert v[0].bvps is None                            # NaN 寫成 NULL
