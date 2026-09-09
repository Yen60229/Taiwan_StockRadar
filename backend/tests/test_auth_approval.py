"""
註冊核准制的測試（06-auth-hardening.md M1）。

這些是本專案第一批真的碰資料庫的測試，用的是 M0 建好的 db_session /
db_client fixture（每個測試包在一個交易裡，結束整個 rollback）。

重點涵蓋的安全性質：
  - 註冊不會拿到 token（不能自助開通）
  - pending / rejected / disabled 都無法登入，也無法用既有 token 讀資料
  - 停權是「立即」生效的，不是等 token 過期
  - 密碼錯誤與帳號待審核的回應要分得開，但**必須先驗密碼**，
    否則登入端點會變成帳號探測工具
  - 一般使用者打管理端點一律 403
  - 管理員不能把自己停用（把自己鎖在外面）
"""
import uuid

import pytest
from sqlalchemy import select

from api.deps import create_access_token, hash_password
from models.database import (
    ROLE_ADMIN, ROLE_USER, STATUS_ACTIVE, STATUS_DISABLED, STATUS_PENDING,
    STATUS_REJECTED, User, Watchlist,
)

PASSWORD = "correct-horse-battery-staple"


async def _make_user(db_session, *, email=None, role=ROLE_USER, status=STATUS_ACTIVE,
                     password=PASSWORD) -> User:
    user = User(
        email=email or f"{uuid.uuid4().hex[:12]}@example.com",
        hashed_pw=await hash_password(password),
        name="測試用",
        role=role,
        status=status,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


def _auth(user: User) -> dict:
    return {"Authorization": f"Bearer {create_access_token(user.id, user.email)}"}


# ── 註冊 ──────────────────────────────────────────────────────
async def test_register_does_not_return_a_token(db_client):
    r = await db_client.post("/api/auth/register", json={
        "email": "newcomer@example.com", "password": PASSWORD, "name": "新來的",
    })

    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "pending_approval"
    assert "access_token" not in body, "註冊不能直接發 token，否則核准制形同虛設"


async def test_register_creates_pending_user(db_client, db_session):
    await db_client.post("/api/auth/register", json={
        "email": "newcomer@example.com", "password": PASSWORD,
    })

    user = (await db_session.execute(
        select(User).where(User.email == "newcomer@example.com")
    )).scalar_one()
    assert user.status == STATUS_PENDING
    assert user.role == ROLE_USER, "新帳號絕不能自動拿到管理員權限"


async def test_duplicate_email_returns_409(db_client, db_session):
    await _make_user(db_session, email="taken@example.com")

    r = await db_client.post("/api/auth/register", json={
        "email": "taken@example.com", "password": PASSWORD,
    })
    assert r.status_code == 409


# ── 登入 ──────────────────────────────────────────────────────
async def test_pending_user_cannot_log_in(db_client, db_session):
    user = await _make_user(db_session, status=STATUS_PENDING)

    r = await db_client.post("/api/auth/login",
                             json={"email": user.email, "password": PASSWORD})

    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "pending_approval"


@pytest.mark.parametrize("status,expected_code", [
    (STATUS_REJECTED, "registration_rejected"),
    (STATUS_DISABLED, "account_disabled"),
])
async def test_rejected_and_disabled_users_cannot_log_in(
    db_client, db_session, status, expected_code
):
    user = await _make_user(db_session, status=status)

    r = await db_client.post("/api/auth/login",
                             json={"email": user.email, "password": PASSWORD})

    assert r.status_code == 403
    assert r.json()["detail"]["code"] == expected_code


async def test_active_user_can_log_in(db_client, db_session):
    user = await _make_user(db_session, status=STATUS_ACTIVE)

    r = await db_client.post("/api/auth/login",
                             json={"email": user.email, "password": PASSWORD})

    assert r.status_code == 200
    assert r.json()["access_token"]
    assert r.json()["user"]["status"] == STATUS_ACTIVE


async def test_wrong_password_on_pending_account_reveals_nothing(db_client, db_session):
    """
    回歸測試：密碼要先驗、狀態後看。
    否則不知道密碼的人可以靠「401 還是 403」問出某個 email 是否存在、
    是否在等待審核——登入端點就變成帳號探測工具。
    """
    user = await _make_user(db_session, status=STATUS_PENDING)

    r = await db_client.post("/api/auth/login",
                             json={"email": user.email, "password": "wrong-password"})

    assert r.status_code == 401, "密碼錯就該回 401，不能洩漏帳號的審核狀態"
    assert "pending" not in r.text


async def test_login_updates_last_login_at(db_client, db_session):
    user = await _make_user(db_session)
    assert user.last_login_at is None

    await db_client.post("/api/auth/login",
                         json={"email": user.email, "password": PASSWORD})

    await db_session.refresh(user)
    assert user.last_login_at is not None


# ── 既有 token 遇到狀態變更 ───────────────────────────────────
async def test_disabling_a_user_invalidates_their_existing_token(db_client, db_session):
    """
    停權必須「立刻」生效。token 有效期 7 天，如果只在登入時檢查狀態，
    被停權的人手上那張還沒過期的 token 就能繼續用一整週。
    """
    user = await _make_user(db_session, status=STATUS_ACTIVE)
    headers = _auth(user)

    assert (await db_client.get("/api/auth/me", headers=headers)).status_code == 200

    user.status = STATUS_DISABLED
    await db_session.commit()

    r = await db_client.get("/api/auth/me", headers=headers)
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "account_disabled"


# ── 資料 API 現在都要登入 ─────────────────────────────────────
@pytest.mark.parametrize("path", [
    "/api/screen",
    "/api/screen/industries",
    "/api/stocks/2330",
    "/api/watchlist",
])
async def test_data_endpoints_require_authentication(db_client, path):
    """這就是『知道網址就連得到』的修復——curl 直接打要拿不到資料"""
    r = await db_client.get(path)
    assert r.status_code == 401, f"{path} 沒有擋住未登入的請求"


async def test_data_endpoints_work_for_active_user(db_client, db_session):
    user = await _make_user(db_session)
    r = await db_client.get("/api/screen", headers=_auth(user))
    assert r.status_code == 200


# ── 管理端點 ──────────────────────────────────────────────────
async def test_normal_user_cannot_access_admin_endpoints(db_client, db_session):
    user = await _make_user(db_session, role=ROLE_USER)

    r = await db_client.get("/api/admin/users", headers=_auth(user))

    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "admin_required"


async def test_admin_can_list_users(db_client, db_session):
    admin = await _make_user(db_session, role=ROLE_ADMIN)
    await _make_user(db_session, status=STATUS_PENDING)

    r = await db_client.get("/api/admin/users", params={"status": STATUS_PENDING},
                            headers=_auth(admin))

    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 1
    assert rows[0]["status"] == STATUS_PENDING


async def test_approve_lets_the_user_log_in(db_client, db_session):
    """整條流程的驗收：申請 → 被擋 → 管理員核准 → 進得來"""
    admin = await _make_user(db_session, role=ROLE_ADMIN)
    applicant = await _make_user(db_session, status=STATUS_PENDING)

    before = await db_client.post("/api/auth/login",
                                  json={"email": applicant.email, "password": PASSWORD})
    assert before.status_code == 403

    approve = await db_client.post(f"/api/admin/users/{applicant.id}/approve",
                                   headers=_auth(admin))
    assert approve.status_code == 200
    assert approve.json()["status"] == STATUS_ACTIVE

    after = await db_client.post("/api/auth/login",
                                 json={"email": applicant.email, "password": PASSWORD})
    assert after.status_code == 200


async def test_approve_records_who_approved(db_client, db_session):
    admin = await _make_user(db_session, role=ROLE_ADMIN)
    applicant = await _make_user(db_session, status=STATUS_PENDING)

    await db_client.post(f"/api/admin/users/{applicant.id}/approve", headers=_auth(admin))

    await db_session.refresh(applicant)
    assert applicant.approved_by == admin.id
    assert applicant.approved_at is not None


async def test_admin_cannot_disable_themselves(db_client, db_session):
    """
    沒有這個保護，唯一的管理員可以在兩次點擊內把自己鎖在系統外，
    而且沒有任何 UI 救得回來——只剩 SSH 進機器改資料庫。
    """
    admin = await _make_user(db_session, role=ROLE_ADMIN)

    r = await db_client.post(f"/api/admin/users/{admin.id}/disable", headers=_auth(admin))

    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "cannot_target_self"

    await db_session.refresh(admin)
    assert admin.status == STATUS_ACTIVE


async def test_admin_can_disable_someone_else(db_client, db_session):
    admin = await _make_user(db_session, role=ROLE_ADMIN)
    victim = await _make_user(db_session, status=STATUS_ACTIVE)

    r = await db_client.post(f"/api/admin/users/{victim.id}/disable", headers=_auth(admin))

    assert r.status_code == 200
    await db_session.refresh(victim)
    assert victim.status == STATUS_DISABLED


async def test_admin_endpoints_reject_unknown_user_id(db_client, db_session):
    admin = await _make_user(db_session, role=ROLE_ADMIN)

    r = await db_client.post(f"/api/admin/users/{uuid.uuid4()}/approve",
                             headers=_auth(admin))
    assert r.status_code == 404


# ── 刪除帳號 ──────────────────────────────────────────────────
async def test_admin_cannot_delete_themselves(db_client, db_session):
    """跟不能停用自己同一個道理：唯一的管理員不該有辦法把自己刪光。"""
    admin = await _make_user(db_session, role=ROLE_ADMIN)

    r = await db_client.delete(f"/api/admin/users/{admin.id}", headers=_auth(admin))

    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "cannot_target_self"

    still_there = (await db_session.execute(
        select(User).where(User.id == admin.id)
    )).scalar_one_or_none()
    assert still_there is not None


async def test_admin_can_delete_a_user_and_row_is_gone_from_db(db_client, db_session):
    """
    這裡刻意不是「status 變成某個值」，而是真的去資料庫確認那一列不見了——
    這支端點的重點就是硬刪除，跟停用（status=disabled，可還原）是不同的動作，
    測試也要證明兩者不同，不能只測回應碼是 204。
    """
    admin  = await _make_user(db_session, role=ROLE_ADMIN)
    victim = await _make_user(db_session, status=STATUS_ACTIVE)
    victim_id = victim.id

    r = await db_client.delete(f"/api/admin/users/{victim_id}", headers=_auth(admin))

    assert r.status_code == 204
    gone = (await db_session.execute(
        select(User).where(User.id == victim_id)
    )).scalar_one_or_none()
    assert gone is None


async def test_deleting_a_user_also_deletes_their_watchlist(db_client, db_session):
    """
    watchlist.user_id 沒有資料庫層的 FK（歷史遺留），刪除使用者不會被
    Postgres 自動連坐清掉——這行為要靠應用程式碼自己做對，所以要有測試
    鎖住它，不然日後很容易在重構時漏掉，留下永遠對不到人的孤兒列。
    """
    admin  = await _make_user(db_session, role=ROLE_ADMIN)
    victim = await _make_user(db_session, status=STATUS_ACTIVE)
    db_session.add(Watchlist(user_id=victim.id, stock_code="2330"))
    await db_session.commit()

    r = await db_client.delete(f"/api/admin/users/{victim.id}", headers=_auth(admin))
    assert r.status_code == 204

    leftover = (await db_session.execute(
        select(Watchlist).where(Watchlist.user_id == victim.id)
    )).scalars().all()
    assert leftover == []


async def test_deleting_unknown_user_id_is_404(db_client, db_session):
    admin = await _make_user(db_session, role=ROLE_ADMIN)

    r = await db_client.delete(f"/api/admin/users/{uuid.uuid4()}", headers=_auth(admin))
    assert r.status_code == 404


async def test_normal_user_cannot_delete_accounts(db_client, db_session):
    normal = await _make_user(db_session, role=ROLE_USER, status=STATUS_ACTIVE)
    victim = await _make_user(db_session, status=STATUS_ACTIVE)

    r = await db_client.delete(f"/api/admin/users/{victim.id}", headers=_auth(normal))
    assert r.status_code == 403


async def test_there_is_no_api_to_grant_admin(db_client, db_session):
    """
    刻意的設計：管理員只能用 CLI（scripts/make_admin.py）建立。
    這個測試會在有人日後不小心加了「升級為管理員」的端點時失敗。
    """
    r = await db_client.get("/openapi.json")
    paths = r.json()["paths"]

    suspicious = [p for p in paths if "admin" in p and any(
        word in p.lower() for word in ("promote", "grant", "role")
    )]
    assert suspicious == [], f"出現了可以透過 API 取得管理權的端點：{suspicious}"
