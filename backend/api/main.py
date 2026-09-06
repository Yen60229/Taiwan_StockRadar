"""
StockRadar - FastAPI 主程式
啟動：uvicorn api.main:app --reload --port 8000
"""
import os
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from api.routes import auth, screen, stocks, watchlist
from models.database import AsyncSessionLocal, init_db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("stockradar")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 StockRadar API starting...")
    if os.environ.get("APP_ENV") != "production":
        await init_db()
    yield
    logger.info("👋 StockRadar API shutting down")


app = FastAPI(
    title="StockRadar API",
    version="1.0.0",
    description="台灣上市櫃股市選股篩選系統 API",
    lifespan=lifespan,
)

# CORS
cors_origins = os.environ.get(
    "CORS_ORIGINS", "http://localhost:3000,http://localhost:5173"
).split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 路由
app.include_router(auth.router)
app.include_router(screen.router)
app.include_router(stocks.router)
app.include_router(watchlist.router)


@app.get("/")
async def root():
    return {
        "name": "StockRadar API",
        "version": "1.0.0",
        "docs": "/docs",
        "endpoints": {
            "auth":      "/api/auth/{register,login,me}",
            "screen":    "/api/screen",
            "stocks":    "/api/stocks/{code}",
            "watchlist": "/api/watchlist",
        },
    }


@app.get("/healthz")
async def healthz():
    """process 存活探針（不碰 DB）"""
    return {"status": "ok"}


@app.get("/api/health")
async def api_health():
    """
    健康檢查（含 DB 連線）。走 /api/ 前綴才會被 Caddy 路由到後端；
    /healthz 在 Caddy 後面會落到 nginx 的 SPA fallback 回 200，不能拿來監控。
    """
    try:
        async with AsyncSessionLocal() as s:
            await s.execute(text("SELECT 1"))
        db_ok = True
    except Exception as e:  # 健康檢查要吞掉所有錯誤回 503
        logger.warning(f"/api/health DB check failed: {e}")
        db_ok = False
    return JSONResponse(
        status_code=200 if db_ok else 503,
        content={
            "status":    "ok" if db_ok else "degraded",
            "db":        db_ok,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    )
