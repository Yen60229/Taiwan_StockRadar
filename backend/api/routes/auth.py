"""
StockRadar - Auth Routes
POST /api/auth/register   送出帳號申請（不會直接開通）
POST /api/auth/login
GET  /api/auth/me
"""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import (
    status_code_for,
    status_message_for,
    create_access_token,
    get_current_user,
    get_db_session,
    hash_password,
    verify_password,
)
from api.schemas import RegisterResponse, TokenResponse, UserLogin, UserOut, UserRegister
from models.database import ROLE_ADMIN, STATUS_PENDING, User
from notifier.account_emails import notify_admins_new_registration

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/register", response_model=RegisterResponse, status_code=201)
async def register(
    payload: UserRegister,
    db: AsyncSession = Depends(get_db_session),
):
    """
    送出帳號申請。**刻意不回傳 token**——帳號建立時是 pending 狀態，
    要等管理員核准才能登入（見 docs/roadmap/06-auth-hardening.md）。
    """
    # 不做 check-then-insert（兩個請求同時通過檢查就會重複）；
    # 直接 insert，靠 users.email 的 UNIQUE 約束擋重複，衝突回 409。
    user = User(
        email=payload.email,
        hashed_pw=await hash_password(payload.password),
        name=payload.name,
        status=STATUS_PENDING,
    )
    db.add(user)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(409, "Email 已註冊")
    await db.refresh(user)

    admin_emails = (await db.execute(
        select(User.email).where(User.role == ROLE_ADMIN)
    )).scalars().all()
    await notify_admins_new_registration(list(admin_emails), user.email, user.name)

    return RegisterResponse()


@router.post("/login", response_model=TokenResponse)
async def login(
    payload: UserLogin,
    db: AsyncSession = Depends(get_db_session),
):
    result = await db.execute(select(User).where(User.email == payload.email))
    user = result.scalar_one_or_none()

    # 先驗密碼、再看狀態，順序不能反：否則不知道密碼的人也能靠回應差異
    # 問出「這個 email 是不是在等待審核」，等於一個帳號探測管道。
    if not user or not await verify_password(payload.password, user.hashed_pw):
        raise HTTPException(401, "Email 或密碼錯誤")

    if not user.can_login:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": status_code_for(user.status),
                    "message": status_message_for(user.status)},
        )

    user.last_login_at = datetime.utcnow()
    await db.commit()
    await db.refresh(user)

    token = create_access_token(user.id, user.email)
    return TokenResponse(access_token=token, user=UserOut.model_validate(user))


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(get_current_user)):
    return user
