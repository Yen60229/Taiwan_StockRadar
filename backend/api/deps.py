"""
StockRadar - 共用依賴 (FastAPI Depends)
- get_db_session: 資料庫 session
- get_current_user: 從 JWT 解出當前使用者
- create_access_token: 簽發 JWT
- hash_password / verify_password
"""
import asyncio
import os
from datetime import datetime, timedelta, timezone
from typing import AsyncGenerator, Optional
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
import bcrypt as _bcrypt
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.database import (
    STATUS_DISABLED, STATUS_PENDING, STATUS_REJECTED, AsyncSessionLocal, User,
)

SECRET_KEY = os.environ.get("SECRET_KEY")
# 未設定、或原封不動照抄 .env.example 的樣板值，都拒絕啟動：
# 兩者都等於「任何人都能簽發合法 token」。
_PLACEHOLDER_KEYS = {
    "change-me",
    "change-me-in-production",
    "change-me-use-a-long-random-string",
}
if not SECRET_KEY or SECRET_KEY.strip().lower() in _PLACEHOLDER_KEYS:
    raise RuntimeError(
        "SECRET_KEY 未設定或仍是樣板值，拒絕啟動。"
        "請在 .env 填入隨機值（openssl rand -base64 48）"
    )
ALGORITHM  = os.environ.get("ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.environ.get("ACCESS_TOKEN_EXPIRE_MINUTES", "10080"))

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)


# ── DB Session ───────────────────────────────────────────────
async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


# ── 密碼處理（直接用 bcrypt，跳過 passlib 相容性問題）────────
# bcrypt 是刻意設計成慢的 CPU-bound 運算（~100ms），直接呼叫會卡住 event loop，
# 所以丟到 thread pool 執行。
async def hash_password(password: str) -> str:
    return await asyncio.to_thread(
        lambda: _bcrypt.hashpw(password.encode(), _bcrypt.gensalt()).decode()
    )


async def verify_password(plain: str, hashed: str) -> bool:
    return await asyncio.to_thread(_bcrypt.checkpw, plain.encode(), hashed.encode())


# ── JWT ──────────────────────────────────────────────────────
def create_access_token(user_id: UUID, email: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {
        "sub":   str(user_id),
        "email": email,
        "exp":   expire,
        "iat":   datetime.now(timezone.utc),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


async def get_current_user(
    token: Optional[str] = Depends(oauth2_scheme),
    db:    AsyncSession  = Depends(get_db_session),
) -> User:
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")

    cred_exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        # sub 缺少或不是合法 UUID 都視為壞 token → 401，而不是讓 ValueError 變成 500
        user_id = UUID(str(payload.get("sub") or ""))
    except (JWTError, ValueError):
        raise cred_exc

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise cred_exc

    # 狀態檢查放在這裡，而不是只在登入時檢查一次：token 有效期 7 天，
    # 管理員停權一個帳號後，那個人手上的舊 token 必須「立刻」失效，
    # 而不是等到 token 過期或他下次登入才生效。
    if not user.can_login:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": status_code_for(user.status),
                    "message": status_message_for(user.status)},
        )
    return user


def status_code_for(user_status: str) -> str:
    return {
        STATUS_PENDING:  "pending_approval",
        STATUS_REJECTED: "registration_rejected",
        STATUS_DISABLED: "account_disabled",
    }.get(user_status, "account_not_active")


def status_message_for(user_status: str) -> str:
    return {
        STATUS_PENDING:  "帳號尚未通過審核，管理員核准後你會收到通知信",
        STATUS_REJECTED: "這個帳號的申請未通過審核",
        STATUS_DISABLED: "這個帳號已被停用",
    }.get(user_status, "帳號目前無法使用")


async def require_admin(user: User = Depends(get_current_user)) -> User:
    """
    管理端點用的依賴。get_current_user 已經確保「登入有效且帳號可用」，
    這裡只再多問一句「是不是管理員」。

    M2 會在這裡再加上「而且已經啟用 2FA」的檢查（見 06-auth-hardening.md）。
    """
    if not user.is_admin:
        # 刻意回 403 而不是 404：對方確實通過身分驗證了，只是權限不足。
        # 這裡不需要隱藏管理端點的存在——路徑本來就寫在公開的 OpenAPI 文件裡。
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "admin_required", "message": "需要管理員權限"},
        )
    return user


async def get_current_user_optional(
    token: Optional[str] = Depends(oauth2_scheme),
    db:    AsyncSession  = Depends(get_db_session),
) -> Optional[User]:
    """登入是選填（用於可匿名瀏覽的 endpoint）"""
    if not token:
        return None
    try:
        return await get_current_user(token, db)
    except HTTPException:
        return None
