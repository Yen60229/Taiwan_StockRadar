"""
不需要資料庫的 API 測試。

主要涵蓋 P0-5：偽造 / 格式錯誤的 token 必須一律回 401。
原本 `UUID(payload["sub"])` 沒有被 try 包住，簽章正確但 sub 不是 UUID 時會
拋 ValueError → 500，把內部錯誤洩漏給呼叫端。

這些路徑在查資料庫之前就結束了，所以不需要真的 DB 也能測。
"""
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from jose import jwt

import api.deps as deps
import api.main as main
from api.main import app


@pytest.fixture
async def client():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def _token(sub: str, key: str | None = None) -> str:
    return jwt.encode(
        {
            "sub": sub,
            "email": "someone@example.com",
            "exp": datetime.now(timezone.utc) + timedelta(minutes=30),
            "iat": datetime.now(timezone.utc),
        },
        key or deps.SECRET_KEY,
        algorithm=deps.ALGORITHM,
    )


# ── 健康檢查 ──────────────────────────────────────────────────
async def test_healthz_does_not_touch_db(client):
    r = await client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


async def test_api_health_reports_503_when_db_unreachable(client, monkeypatch):
    """
    /api/health 會 SELECT 1。DB 掛掉時要回 503（讓 container 被判 unhealthy、
    讓外部監控抓得到），而不是拋例外或假裝正常。
    """
    class _Boom:
        def __call__(self):
            raise OSError("connection refused")

    monkeypatch.setattr(main, "AsyncSessionLocal", _Boom())
    r = await client.get("/api/health")

    assert r.status_code == 503
    body = r.json()
    assert body["status"] == "degraded"
    assert body["db"] is False
    assert "timestamp" in body


# ── Token 驗證（P0-5）─────────────────────────────────────────
async def test_missing_token_returns_401(client):
    r = await client.get("/api/auth/me")
    assert r.status_code == 401


@pytest.mark.parametrize("bad", [
    "not-a-jwt",
    "aaa.bbb.ccc",
    "",
])
async def test_malformed_token_returns_401(client, bad):
    r = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {bad}"})
    assert r.status_code == 401


async def test_token_signed_with_wrong_key_returns_401(client):
    r = await client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {_token('11111111-1111-1111-1111-111111111111', key='someone-elses-key')}"},
    )
    assert r.status_code == 401


@pytest.mark.parametrize("sub", ["not-a-uuid", "", "12345", "'; DROP TABLE users;--"])
async def test_valid_signature_but_bad_sub_returns_401_not_500(client, sub):
    """
    回歸測試（P0-5）：簽章正確但 sub 不是合法 UUID 時，
    舊版會在 UUID(user_id) 拋 ValueError → 500。現在必須是 401。
    """
    r = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {_token(sub)}"})
    assert r.status_code == 401, f"sub={sub!r} 應回 401，實際 {r.status_code}"


async def test_expired_token_returns_401(client):
    expired = jwt.encode(
        {
            "sub": "11111111-1111-1111-1111-111111111111",
            "exp": datetime.now(timezone.utc) - timedelta(minutes=1),
        },
        deps.SECRET_KEY,
        algorithm=deps.ALGORITHM,
    )
    r = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {expired}"})
    assert r.status_code == 401


# ── 路由註冊 ──────────────────────────────────────────────────
async def test_expected_routes_are_registered(client):
    r = await client.get("/openapi.json")
    assert r.status_code == 200
    paths = r.json()["paths"]

    for expected in [
        "/api/health",
        "/api/auth/register",
        "/api/auth/login",
        "/api/auth/me",
        "/api/screen",
        "/api/watchlist",
    ]:
        assert expected in paths, f"{expected} 未註冊"
