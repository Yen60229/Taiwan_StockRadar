"""
測試共用設定。

⚠️ SECRET_KEY 必須在匯入任何 api 模組「之前」設好：
   api.deps 在 import 當下就會檢查，沒設或還是樣板值會直接 RuntimeError
   （這正是 P0-3 的預期行為，見 test_config_guard.py）。
"""
import json
import os
import pathlib

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

os.environ.setdefault("SECRET_KEY", "test-only-secret-do-not-use-in-production")
os.environ.setdefault(
    "DATABASE_URL", "postgresql+asyncpg://stockradar:test@127.0.0.1:5432/stockradar_test"
)
# production 模式讓 lifespan 不會嘗試建表（ASGITransport 本來就不跑 lifespan，雙保險）
os.environ.setdefault("APP_ENV", "production")

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


class _Fixtures:
    """讀取 tests/fixtures/ 下的真實 API 樣本"""

    dir = FIXTURES

    @staticmethod
    def json(name: str):
        return json.loads((FIXTURES / name).read_text(encoding="utf-8"))

    @staticmethod
    def text(name: str) -> str:
        return (FIXTURES / name).read_text(encoding="utf-8")


@pytest.fixture(scope="session")
def fx() -> type[_Fixtures]:
    return _Fixtures


# ── DB 測試地基（06-auth-hardening.md M0）─────────────────────
#
# 需要一個真的 PostgreSQL（DATABASE_URL 指到它）才能跑這裡的 fixture。
# 沒有 DB 的環境下，只用 `fx` 的離線測試完全不受影響。
#
# 設計：
#   1. schema 一律由 `alembic upgrade head` 建立（session 開始時跑一次），
#      不用 create_all() —— 這樣測試驗證的才是 production 真正會跑的 migration，
#      而不是另一條可能跟 migration 漂移的建表路徑。
#   2. 每個測試包在自己的交易裡，測試結束就 rollback，測試之間互不污染，
#      不需要每次測試都清空/重建整個資料庫。
#      這是 SQLAlchemy 官方文件「Joining a Session into an External
#      Transaction」的標準寫法：外層開一個真交易，Session 綁在同一個
#      connection 上；即使程式碼呼叫了 session.commit()，也只是關閉並重開
#      一個 SAVEPOINT，最外層的交易到最後仍然整個 rollback。


@pytest.fixture(scope="session")
def _migrated_db_url() -> str:
    """
    Session 開始時跑一次 `alembic upgrade head`，回傳驗證過的 DATABASE_URL。

    刻意寫成同步 fixture：run_upgrade_head() 內部自己呼叫 asyncio.run()
    （見 scripts/alembic_utils.py 的說明），不能在任何已經在跑的
    event loop 裡呼叫——同步 fixture 保證這裡還沒有 event loop。
    """
    from scripts.alembic_utils import run_upgrade_head

    db_url = os.environ["DATABASE_URL"]
    run_upgrade_head(db_url)
    return db_url


@pytest_asyncio.fixture
async def db_session(_migrated_db_url):
    """
    一個包在單一交易裡的 AsyncSession，測試結束自動 rollback。

    程式碼中的 `await session.commit()` 不會真的落地，而是關掉目前的
    SAVEPOINT、立刻開一個新的——`after_transaction_end` 這個監聽器就是在做
    這件事。呼叫端可以像平常一樣呼叫 commit()，不用為了測試改寫成別的樣子。
    """
    engine = create_async_engine(_migrated_db_url)
    async with engine.connect() as conn:
        outer_tx = await conn.begin()
        await conn.begin_nested()  # SAVEPOINT

        session = AsyncSession(bind=conn, expire_on_commit=False)

        @event.listens_for(session.sync_session, "after_transaction_end")
        def _restart_savepoint(sess, transaction):
            if transaction.nested and not transaction._parent.nested:
                sess.begin_nested()

        try:
            yield session
        finally:
            await session.close()
            await outer_tx.rollback()
    await engine.dispose()


@pytest_asyncio.fixture
async def db_client(db_session):
    """
    像 test_api_offline.py 的 client fixture，但額外把 get_db_session
    換成這個測試專用、會 rollback 的 db_session——需要真的碰資料庫的
    端點測試（auth / screen / watchlist，見 06-auth-hardening.md M1）用這個。
    """
    from api.deps import get_db_session
    from api.main import app

    async def _override():
        yield db_session

    app.dependency_overrides[get_db_session] = _override
    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            yield c
    finally:
        app.dependency_overrides.pop(get_db_session, None)
