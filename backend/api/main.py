"""
StockRadar - FastAPI 主程式
啟動：uvicorn api.main:app --reload --port 8000
"""
import os
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from api.routes import auth, screen, stocks, watchlist
from models.database import init_db

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
    return {"status": "ok"}
