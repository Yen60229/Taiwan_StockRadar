"""
StockRadar - Auth Routes
POST /api/auth/register
POST /api/auth/login
GET  /api/auth/me
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import (
    create_access_token,
    get_current_user,
    get_db_session,
    hash_password,
    verify_password,
)
from api.schemas import TokenResponse, UserLogin, UserOut, UserRegister
from models.database import User

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/register", response_model=TokenResponse, status_code=201)
async def register(
    payload: UserRegister,
    db: AsyncSession = Depends(get_db_session),
):
    # 不做 check-then-insert（兩個請求同時通過檢查就會重複）；
    # 直接 insert，靠 users.email 的 UNIQUE 約束擋重複，衝突回 409。
    user = User(
        email=payload.email,
        hashed_pw=await hash_password(payload.password),
        name=payload.name,
    )
    db.add(user)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(409, "Email 已註冊")
    await db.refresh(user)

    token = create_access_token(user.id, user.email)
    return TokenResponse(access_token=token, user=UserOut.model_validate(user))


@router.post("/login", response_model=TokenResponse)
async def login(
    payload: UserLogin,
    db: AsyncSession = Depends(get_db_session),
):
    result = await db.execute(select(User).where(User.email == payload.email))
    user = result.scalar_one_or_none()
    if not user or not await verify_password(payload.password, user.hashed_pw):
        raise HTTPException(401, "Email 或密碼錯誤")

    token = create_access_token(user.id, user.email)
    return TokenResponse(access_token=token, user=UserOut.model_validate(user))


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(get_current_user)):
    return user
