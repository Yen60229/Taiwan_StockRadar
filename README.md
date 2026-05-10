# StockRadar — Taiwan Stock Screener

A self-hosted stock screening tool for the Taiwan market (TWSE + TPEX).  
It pulls chip-concentration and volume data from four public sources every day, lets you filter 1,900+ stocks with adjustable sliders, and sends a weekly email digest.

> 🚧 **Live demo coming in v2** — VPS deployment in progress

[![Python](https://img.shields.io/badge/Python-3.11-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![React](https://img.shields.io/badge/React-18-61DAFB?logo=react&logoColor=black)](https://react.dev/)
[![TypeScript](https://img.shields.io/badge/TypeScript-5.6-3178C6?logo=typescript&logoColor=white)](https://www.typescriptlang.org/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-4169E1?logo=postgresql&logoColor=white)](https://www.postgresql.org/)
[![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?logo=docker&logoColor=white)](https://docs.docker.com/compose/)

---

## Screenshots

![Dashboard](docs/screenshots/dashboard.png)

> Filter bar: drag the sliders to adjust the volume and chip-concentration threshold in real time. Results update instantly without a page reload.

---

## Why I built this

Checking chip concentration for Taiwan stocks by hand means visiting TWSE, TPEX, and TDCC separately — each with a different interface and no way to combine the data. It took over an hour to screen even 50 stocks.

I wanted one tool that pulls all three sources automatically, scores every listed and OTC stock, and lets me tweak the thresholds with a slider instead of a spreadsheet.

---

## Tech highlights

- **Full-stack**: FastAPI (Python 3.11) + PostgreSQL + React + TypeScript, served behind Caddy
- **Concurrent data pipeline**: four scrapers run in parallel with `asyncio.gather` — TWSE quotes, TPEX quotes, TDCC chip distribution, and ownership ratios — finishing all 1,900+ stocks in under 20 minutes
- **Anti-scraping workarounds**: TPEX blocked its main OpenAPI mid-project; switched to ISIN-based queries. TDCC requires a CSRF token per session; the scraper fetches the form page first, extracts the token, then uses it for the actual data request
- **Chip concentration formula**: TDCC's "holders with ≥400 lots" ratio minus foreign-institution holdings = domestic large-holder ratio (the signal retail traders care about most)
- **Resizable columns**: table column widths are draggable, persisted in component state
- **CSV export**: one click downloads the filtered result as UTF-8 BOM CSV (opens correctly in Excel without re-encoding)
- **One-command deploy**: `docker compose up -d` starts PostgreSQL, FastAPI, React (Nginx), and the scheduler together
- **Production HTTPS**: Caddy handles reverse proxying and requests a Let's Encrypt certificate automatically

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│  Browser                                                │
│  React 18 + TypeScript · TanStack Query · Zustand      │
│  Recharts · Axios · Vite                                │
└──────────────────────┬──────────────────────────────────┘
                       │  HTTPS  (Caddy — auto TLS)
┌──────────────────────▼──────────────────────────────────┐
│  FastAPI  (Python 3.11 + uvicorn)                       │
│  ├─ GET  /api/screen         filter stocks              │
│  ├─ GET  /api/stocks/{code}  stock detail               │
│  ├─ *    /api/watchlist      personal watchlist CRUD    │
│  └─ POST /api/auth/*         JWT register / login       │
└──────────────────────┬──────────────────────────────────┘
                       │  asyncpg / SQLAlchemy (async)
┌──────────────────────▼──────────────────────────────────┐
│  PostgreSQL 16   (Docker volume, persisted)             │
└─────────────────────────────────────────────────────────┘

  Scraper services  (Docker scheduler, runs on weekends)
  ┌─────────────────────────────────────────────────┐
  │  twse_scraper.py      TWSE daily quotes         │
  │  tpex_scraper.py      TPEX daily quotes (ISIN)  │
  │  tdcc_scraper.py      Chip distribution table   │
  │  ownership_scraper.py Institutional ownership   │
  │          └── data_pipeline.py → PostgreSQL      │
  └─────────────────────────────────────────────────┘
```

---

## Key design decisions

**Why store daily quotes instead of fetching live?**  
Computing a 20-day average volume requires 20 rows of history. Neither TWSE nor TPEX provides moving averages via their APIs, so we accumulate rows over time and compute them in SQL. This also keeps the app working when either exchange's API is temporarily slow.

**Why switch from TPEX's OpenAPI to ISIN-based queries?**  
TPEX started blocking automated requests on their main endpoint during development. The ISIN-code endpoint remained accessible, so we use stock ISIN codes to fetch data instead of the direct symbol lookup.

**Why separate `name` and `short_name` columns?**  
A company's legal registered name (e.g., "台灣積體電路製造股份有限公司") and its market display name ("台積電") are different things. Mixing them causes UI truncation and keyword search mismatches.

**Why a separate scheduler Docker service?**  
Keeps the cron job isolated from the API process. If the API restarts during development, the scheduler keeps running. In production they also restart independently, so a scraper crash doesn't take the API down with it.

---

## Challenges along the way

| Problem | Solution |
|---------|----------|
| Cloudflare blocking TDCC requests | Added realistic browser headers + 1.5 s delay between calls |
| Some TPEX responses use Big5 encoding | Explicit `response.content.decode("big5")` instead of auto-detect |
| TDCC CSRF token expires every session | Scraper fetches the form page first, extracts the token, then sends the data request |
| TPEX OpenAPI endpoint blocked mid-project | Switched to ISIN-based queries on an unblocked endpoint |

---

## Quick start

**Requirements**: Docker Desktop (Compose v2 included)

```bash
# 1. Clone the repo
git clone https://github.com/Yen60229/taiwan-stock-radar.git
cd taiwan-stock-radar

# 2. Create your environment file
cp .env.example .env
# Open .env and set DB_PASSWORD and SECRET_KEY at minimum

# 3. Start all services
docker compose up -d

# 4. Backfill 2 months of history (first run only — takes ~20 min)
docker compose exec api python scripts/backfill_history.py

# 5. Open the app
#    http://localhost:3000
```

Register your account at `POST /api/auth/register` (or via the login page's register link).

---

## Production deploy (VPS + HTTPS)

Full walkthrough: [docs/deploy-to-vps.md](docs/deploy-to-vps.md)

Short version:

```bash
git clone https://github.com/Yen60229/taiwan-stock-radar.git /opt/stockradar
cd /opt/stockradar
cp .env.example .env
# Set DOMAIN, DB_PASSWORD, SECRET_KEY, TLS_EMAIL
docker compose -f docker-compose.prod.yml up -d --build
```

Caddy requests a Let's Encrypt certificate automatically. The site goes live in about 30 seconds after DNS propagates.

---

## Environment variables

| Variable | Required | Description |
|----------|----------|-------------|
| `DB_PASSWORD` | ✅ | PostgreSQL password |
| `SECRET_KEY` | ✅ | JWT signing key (`openssl rand -base64 48`) |
| `DOMAIN` | Production | Your domain, e.g. `stockradar.tw` — used by Caddy for TLS |
| `TLS_EMAIL` | Production | Email for Let's Encrypt notifications |
| `RESEND_API_KEY` | Optional | Weekly email digest via [resend.com](https://resend.com) |
| `EMAIL_FROM` | Optional | Sender address for email reports |

---

## Project structure

```
taiwan-stock-radar/
├── backend/
│   ├── api/              # FastAPI routes: auth / screen / stocks / watchlist
│   ├── models/           # SQLAlchemy models + database initialization
│   ├── scraper/          # TWSE / TPEX / TDCC / ownership scrapers
│   ├── pipeline/         # aggregation pipeline + history backfill
│   ├── notifier/         # weekly email report (Resend + Jinja2 template)
│   ├── scripts/          # cron entry point / manual trigger scripts
│   ├── Dockerfile
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── api/          # Axios client + TypeScript type definitions
│   │   ├── pages/        # DashboardPage / StockPage / LoginPage
│   │   └── store/        # Zustand auth store
│   ├── Dockerfile
│   └── package.json
├── docs/
│   └── deploy-to-vps.md
├── docker-compose.yml          # local development
├── docker-compose.prod.yml     # production (Caddy + HTTPS)
├── Caddyfile
└── .env.example
```

---

## Data sources

All data comes from publicly available sources — no paid APIs required.

| Source | What it provides |
|--------|-----------------|
| [TWSE OpenAPI](https://openapi.twse.com.tw/) | Daily quotes for listed stocks (上市) |
| [TPEX OpenAPI](https://www.tpex.org.tw/openapi/) | Daily quotes for OTC stocks (上櫃), ISIN-based |
| [TDCC](https://www.tdcc.com.tw/) | Shareholder distribution by holding tier (chip concentration) |
| [MOPS](https://mops.twse.com.tw/) | Institutional ownership ratios (foreign / directors) |

---

## Roadmap

### v1 — Done ✅

- [x] TWSE + TPEX daily quote scraping
- [x] TDCC chip concentration data
- [x] Institutional ownership ratios (foreign / directors)
- [x] FastAPI + PostgreSQL backend with JWT auth
- [x] React dark-theme dashboard — real-time filter sliders, resizable columns, watchlist, CSV export
- [x] Docker Compose one-command deploy (dev + prod)
- [x] Caddy auto-HTTPS
- [x] Weekly email digest with APScheduler

### v2 — In progress 🚧

- [ ] Live deploy on Hetzner VPS
- [ ] Candlestick chart + chip trend over time (Recharts)
- [ ] Stock detail page — daily institutional buy/sell + weekly chip changes
- [ ] Line Notify / Telegram push alerts
- [ ] Strategy backtesting module

---

## License

MIT © 2026 [Yen60229](https://github.com/Yen60229)
