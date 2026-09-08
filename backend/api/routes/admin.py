"""
StockRadar - Admin Routes（全部需要 role=admin）
GET  /api/admin/users                 使用者清單（可依狀態過濾）
POST /api/admin/users/{id}/approve    核准申請
POST /api/admin/users/{id}/reject     拒絕申請
POST /api/admin/users/{id}/disable    停用帳號
POST /api/admin/users/{id}/enable     重新啟用

管理員本身只能用 CLI 建立（scripts/make_admin.py），這裡沒有「把某人升成
管理員」的端點——避免任何一條「透過 API 就能取得最高權限」的路徑存在。
"""
import logging
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_db_session, require_admin
from api.schemas import AdminUserOut
from models.database import (
    STATUS_ACTIVE, STATUS_DISABLED, STATUS_REJECTED, VALID_STATUSES, User,
)
from notifier.account_emails import notify_user_approved

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin", tags=["admin"])


async def _get_target(db: AsyncSession, user_id: UUID) -> User:
    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if not user:
        raise HTTPException(404, "找不到這個使用者")
    return user


def _refuse_self_target(target: User, admin: User, action: str) -> None:
    """
    不准對自己做停用/拒絕這類動作。
    沒有這個檢查，唯一的管理員可以在兩次點擊之內把自己鎖在系統外面，
    而且沒有任何 UI 能救回來（只剩 SSH 進機器改資料庫）。
    """
    if target.id == admin.id:
        raise HTTPException(
            400, {"code": "cannot_target_self", "message": f"不能對自己{action}"}
        )


@router.get("/users", response_model=list[AdminUserOut])
async def list_users(
    status_filter: str | None = Query(None, alias="status"),
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db_session),
):
    q = select(User).order_by(User.created_at.desc())
    if status_filter:
        if status_filter not in VALID_STATUSES:
            raise HTTPException(400, f"status 只能是 {list(VALID_STATUSES)} 其中之一")
        q = q.where(User.status == status_filter)
    return (await db.execute(q)).scalars().all()


@router.post("/users/{user_id}/approve", response_model=AdminUserOut)
async def approve_user(
    user_id: UUID,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db_session),
):
    target = await _get_target(db, user_id)

    target.status = STATUS_ACTIVE
    target.approved_at = datetime.utcnow()
    target.approved_by = admin.id
    await db.commit()
    await db.refresh(target)

    # 稽核紀錄：事後要查得出「誰在什麼時候放誰進來」
    logger.info(f"[Admin] {admin.email} 核准了 {target.email}")
    await notify_user_approved(target.email, target.name)
    return target


@router.post("/users/{user_id}/reject", response_model=AdminUserOut)
async def reject_user(
    user_id: UUID,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db_session),
):
    target = await _get_target(db, user_id)
    _refuse_self_target(target, admin, "拒絕")

    target.status = STATUS_REJECTED
    await db.commit()
    await db.refresh(target)

    logger.info(f"[Admin] {admin.email} 拒絕了 {target.email}")
    return target


@router.post("/users/{user_id}/disable", response_model=AdminUserOut)
async def disable_user(
    user_id: UUID,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db_session),
):
    target = await _get_target(db, user_id)
    _refuse_self_target(target, admin, "停用")

    target.status = STATUS_DISABLED
    await db.commit()
    await db.refresh(target)

    logger.info(f"[Admin] {admin.email} 停用了 {target.email}")
    return target


@router.post("/users/{user_id}/enable", response_model=AdminUserOut)
async def enable_user(
    user_id: UUID,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db_session),
):
    """把 disabled / rejected 的帳號重新啟用"""
    target = await _get_target(db, user_id)

    target.status = STATUS_ACTIVE
    if target.approved_at is None:
        target.approved_at = datetime.utcnow()
        target.approved_by = admin.id
    await db.commit()
    await db.refresh(target)

    logger.info(f"[Admin] {admin.email} 重新啟用了 {target.email}")
    return target
