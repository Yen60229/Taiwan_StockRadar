# Deploy to a VPS (Caddy + Docker Compose)

From a fresh server to HTTPS in about 30 minutes.

> **Where this project actually runs:** an Oracle Cloud Always Free Ampere A1
> instance (2 OCPU / 12 GB, ARM), not Hetzner. The steps below are the generic
> VPS path and work on either. For the Oracle-specific parts — security lists
> instead of just UFW, the ARM base images, and the retry script for the
> "out of capacity" errors — see
> [`oracle-cloud-automation.md`](./oracle-cloud-automation.md).
>
> The Chinese walkthrough [`部署到VPS.md`](./部署到VPS.md) covers the same ground.

---

## 1. Recommended server specs

| Plan | CPU | RAM | Cost | Notes |
|------|-----|-----|------|-------|
| **CX22** (recommended) | 2 vCPU | 4 GB | ~€3.8/mo | handles daily pipeline comfortably |
| CX32 | 4 vCPU | 8 GB | ~€7.5/mo | if you expect heavier traffic |

**OS**: Ubuntu 22.04 LTS

---

## 2. Set up DNS

After creating the server and noting its public IP, add an A record at your DNS provider:

| Name | Type | Value |
|------|------|-------|
| `@` or `stockradar` | A | your VPS IP |

DNS propagation takes 5–30 minutes. Wait before starting Caddy, or the TLS certificate request will fail.

---

## 3. Initial server setup

```bash
ssh root@<your-vps-ip>

# Update packages
apt update && apt upgrade -y

# Firewall — allow SSH, HTTP, HTTPS
ufw allow ssh
ufw allow 80/tcp
ufw allow 443/tcp
ufw allow 443/udp    # HTTP/3 (QUIC)
ufw --force enable

# Create a non-root user
adduser deploy
usermod -aG sudo deploy
rsync --archive --chown=deploy:deploy ~/.ssh /home/deploy

# Switch to the new user for everything below
su - deploy
```

---

## 4. Install Docker

```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER

# Re-login so the group takes effect
exit
ssh deploy@<your-vps-ip>
docker version   # should work without sudo
```

---

## 5. Deploy the app

```bash
# Clone the repo
git clone https://github.com/Yen60229/taiwan-stock-radar.git /opt/stockradar
cd /opt/stockradar

# Create the environment file
cp .env.example .env
nano .env
```

Minimum required values in `.env`:

```bash
DOMAIN=your-domain.com        # no https://
DB_PASSWORD=<strong-random>   # openssl rand -base64 32
SECRET_KEY=<strong-random>    # openssl rand -base64 48
TLS_EMAIL=your@email.com      # for Let's Encrypt notifications
```

Optional (for weekly email reports):

```bash
RESEND_API_KEY=re_...
EMAIL_FROM=report@your-domain.com
```

```bash
# Build, migrate, and start everything
bash scripts/deploy.sh
```

Use `deploy.sh` rather than `docker compose up -d` directly. It starts PostgreSQL
on its own first, waits until it reports healthy, runs `alembic upgrade head`, and
only then brings up the rest — the API should never issue its first queries against
a database that has no tables yet.

First build takes 3–5 minutes (downloads images and compiles the frontend). After that, Caddy automatically requests a certificate. The site goes live within ~30 seconds.

**Deploying onto a database that predates Alembic?** `alembic upgrade head` will fail
with `DuplicateTableError: relation "stocks" already exists`, because the baseline
migration tries to create tables that are already there. Record the baseline as
applied without running it, then migrate:

```bash
docker compose -f docker-compose.prod.yml run --rm --no-deps api alembic stamp 0944c4e72b5a
docker compose -f docker-compose.prod.yml run --rm --no-deps api alembic upgrade head
```

Check service status:

```bash
docker compose -f docker-compose.prod.yml ps
```

You should see five services all `Up`:

```
NAME        STATUS
postgres    Up (healthy)
api         Up
scheduler   Up
frontend    Up
caddy       Up
```

---

## 6. Backfill history (first deploy only)

The 20-day volume average needs 20 rows of historical data. Run this once:

```bash
docker compose -f docker-compose.prod.yml exec api \
    python scripts/backfill_history.py
```

Takes about 20–30 minutes. You'll see `✅ Done` at the end.

---

## 7. Verify

```bash
curl https://your-domain.com/api/health
# Expected: {"status": "ok", "db": true, "timestamp": "..."}
# (Do NOT use /healthz here: behind Caddy it hits nginx's SPA fallback and always returns 200)
```

Every data endpoint requires a logged-in account, so an unauthenticated request
should be rejected:

```bash
curl -s -o /dev/null -w "%{http_code}
" https://your-domain.com/api/screen
# Expected: 401
```

Open `https://your-domain.com` in a browser. Register an account through the UI,
then promote it — the first admin can't wait for someone else to approve them:

```bash
docker compose -f docker-compose.prod.yml exec api     python -m scripts.make_admin you@example.com
```

`make_admin` also flips the account to active. After that, new applications show up
under 帳號管理 in the UI, and approving one emails the applicant — provided
`RESEND_API_KEY` or `SMTP_USER`/`SMTP_PASS` is set. With neither, approval still
works; the mail is just skipped with a warning in the log.

---

## 8. Day-to-day operations

**Trigger the pipeline manually (without waiting for the cron schedule):**

```bash
docker compose -f docker-compose.prod.yml exec scheduler \
    sh /app/scripts/run_now.sh
```

**Update to the latest code:**

```bash
cd /opt/stockradar
git pull
docker compose -f docker-compose.prod.yml up -d --build
```

**View logs:**

```bash
# All services (live)
docker compose -f docker-compose.prod.yml logs -f

# API only
docker compose -f docker-compose.prod.yml logs -f api
```

**Database backup:**

```bash
docker compose -f docker-compose.prod.yml exec postgres \
    pg_dump -U stockradar stockradar \
    | gzip > backup_$(date +%Y%m%d).sql.gz
```

---

## Troubleshooting

**Caddy can't get a certificate (`TLS handshake error`)**  
→ Check that DNS has propagated: `nslookup your-domain.com` should return your VPS IP.  
→ Check firewall: `ufw status` — ports 80 and 443 must be open.

**API returns 502 Bad Gateway**  
→ `docker compose -f docker-compose.prod.yml logs api | tail -30`

**Dashboard loads but shows no data**  
→ Run the pipeline manually (see above) to populate the database.
