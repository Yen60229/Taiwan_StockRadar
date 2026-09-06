# StockRadar Backend — multi-stage build
#   Stage 1 builder : 裝編譯工具鏈 + pip install，產物放獨立 prefix
#   Stage 2 runtime : 不含編譯工具鏈、以 non-root 執行、附 HEALTHCHECK
# 多數依賴都提供 manylinux wheel（x86_64 與 aarch64/Ampere 皆有），
# 但少數（如 yfinance 的 peewee）只發佈 sdist，需要 gcc，故 builder 仍裝 build-essential。
# psycopg2 已移除（全程 asyncpg），因此不需要 libpq-dev。

# ── Stage 1: builder ──────────────────────────────────────────
FROM python:3.12-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build
COPY requirements.txt .
RUN pip install --prefix=/install -r requirements.txt

# ── Stage 2: runtime ──────────────────────────────────────────
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    TZ=Asia/Taipei

# cron：scheduler container 用；tzdata：時區；curl：HEALTHCHECK 用
RUN apt-get update && apt-get install -y --no-install-recommends \
        cron tzdata curl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --uid 1000 --create-home --shell /usr/sbin/nologin app

COPY --from=builder /install /usr/local

WORKDIR /app
COPY --chown=app:app . .
RUN mkdir -p /app/logs && chown app:app /app/logs

EXPOSE 8000

# /api/health 會 SELECT 1，DB 掛了會回 503 → container unhealthy
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/api/health || exit 1

# API 以 non-root 執行。
# scheduler 因為 cron daemon 需要 root，在 docker-compose 以 `user: root` 覆寫。
USER app

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
