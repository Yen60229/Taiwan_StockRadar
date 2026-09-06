"""
測試共用設定。

⚠️ SECRET_KEY 必須在匯入任何 api 模組「之前」設好：
   api.deps 在 import 當下就會檢查，沒設或還是樣板值會直接 RuntimeError
   （這正是 P0-3 的預期行為，見 test_config_guard.py）。
"""
import json
import pathlib

import pytest

import os

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
