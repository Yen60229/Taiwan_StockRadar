"""
Smoke tests for the DB test infrastructure itself (06-auth-hardening.md M0).

These aren't testing StockRadar's business logic -- they're proof that
`db_session` / `db_client` actually work the way M1's auth/screen/watchlist
tests will need them to:
  1. the migrated schema is really there and usable
  2. each test is isolated (nothing written in one test leaks into another)
  3. commit() inside application code doesn't defeat that isolation
  4. a FastAPI endpoint wired through `db_client` really reads from the
     same transaction the test set up

Requires a real PostgreSQL via DATABASE_URL. Skipped automatically when
none is reachable, so `pytest` stays green on machines without Docker.
"""
from datetime import date
from decimal import Decimal

from sqlalchemy import select, text

from api.deps import create_access_token, hash_password
from models.database import (
    ROLE_USER, STATUS_ACTIVE, ChipConcentration, DailyQuote, Stock, User,
)


async def test_migrated_schema_has_all_seven_tables(db_session):
    rows = (await db_session.execute(
        text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
    )).scalars().all()

    assert set(rows) == {
        "stocks", "daily_quotes", "institutional_flow", "chip_concentration",
        "users", "watchlist", "ownership_ratios", "alembic_version",
    }


async def test_insert_and_read_back(db_session):
    db_session.add(Stock(code="2330", name="台灣積體電路製造股份有限公司",
                          short_name="台積電", market="TWSE", industry="半導體業"))
    await db_session.commit()

    stock = (await db_session.execute(
        select(Stock).where(Stock.code == "2330")
    )).scalar_one()
    assert stock.short_name == "台積電"


async def test_previous_tests_commit_did_not_leak(db_session):
    """
    回歸測試：上一個測試呼叫了 commit()。如果 rollback 機制沒做對
    （例如漏掉 SAVEPOINT 重啟監聽器），這裡會意外看到 2330。
    """
    count = (await db_session.execute(
        select(Stock).where(Stock.code == "2330")
    )).scalars().all()
    assert count == [], "上一個測試的 commit() 不應該留存到這個測試"


async def test_rollback_mid_test_also_does_not_leak(db_session):
    """同一個測試內部主動 rollback，之後的查詢也不該看到未 commit 的資料"""
    db_session.add(Stock(code="9999", name="測試用", market="TWSE"))
    await db_session.flush()
    await db_session.rollback()

    result = (await db_session.execute(
        select(Stock).where(Stock.code == "9999")
    )).scalar_one_or_none()
    assert result is None


async def test_screen_endpoint_reads_from_the_same_transaction(db_client, db_session):
    """
    證明 db_client 的 dependency override 真的接到 db_session 這個交易。

    /api/screen 自 M1 起需要登入（見 06-auth-hardening.md），所以這裡也要
    先建一個 active 使用者、帶著 token 打——順帶證明了 auth 依賴同樣走在
    這個測試交易裡。
    """
    today = date.today()
    user = User(
        email="smoke@example.com",
        hashed_pw=await hash_password("smoke-test-password"),
        role=ROLE_USER,
        status=STATUS_ACTIVE,
    )
    db_session.add_all([
        user,
        Stock(code="2330", name="台積電", short_name="台積電",
              market="TWSE", industry="半導體業"),
        DailyQuote(stock_code="2330", trade_date=today,
                   close=Decimal("1000.00"), volume=50000, avg_vol_20d=Decimal("48000.0")),
        ChipConcentration(stock_code="2330", week_date=today, conc_ratio=Decimal("55.50")),
    ])
    await db_session.commit()
    await db_session.refresh(user)

    headers = {"Authorization": f"Bearer {create_access_token(user.id, user.email)}"}
    r = await db_client.get("/api/screen",
                            params={"min_avg_vol": 0, "min_conc": 0}, headers=headers)
    assert r.status_code == 200

    body = r.json()
    codes = [item["code"] for item in body["items"]]
    assert "2330" in codes, f"預期看到剛寫入的 2330，實際回傳：{codes}"
