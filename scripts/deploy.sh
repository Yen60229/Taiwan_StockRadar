#!/bin/bash
# StockRadar — VPS 部署腳本
# 用法：
#   首次部署：bash scripts/deploy.sh --init
#   日後更新：bash scripts/deploy.sh
#
# 執行環境：Ubuntu 22.04 VPS（Hetzner 等）
# 依賴：Docker >= 24、Docker Compose v2、git

set -euo pipefail

REPO_URL="https://github.com/YOUR_USERNAME/stockradar.git"   # ← 改成你的 GitHub repo
APP_DIR="/opt/stockradar"
COMPOSE_FILE="docker-compose.prod.yml"

RED='\033[0;31m'
GRN='\033[0;32m'
YLW='\033[0;33m'
BLU='\033[0;34m'
NC='\033[0m'

log()  { echo -e "${BLU}[deploy]${NC} $*"; }
ok()   { echo -e "${GRN}[  ok  ]${NC} $*"; }
warn() { echo -e "${YLW}[ warn ]${NC} $*"; }
die()  { echo -e "${RED}[ fail ]${NC} $*"; exit 1; }

# ── 首次初始化 ──────────────────────────────────────────
init() {
    log "首次部署初始化..."

    # 1. 確認 Docker 已裝
    command -v docker &>/dev/null || die "Docker 未安裝，請先執行 install_docker.sh"
    docker compose version &>/dev/null || die "Docker Compose v2 未安裝"

    # 2. 建立應用目錄
    sudo mkdir -p "$APP_DIR"
    sudo chown "$(whoami):$(whoami)" "$APP_DIR"

    # 3. Clone repo
    if [ -d "$APP_DIR/.git" ]; then
        warn "目錄已存在，改用 git pull"
        cd "$APP_DIR" && git pull
    else
        git clone "$REPO_URL" "$APP_DIR"
        cd "$APP_DIR"
    fi

    # 4. 建立 .env
    if [ ! -f "$APP_DIR/.env" ]; then
        cat > "$APP_DIR/.env" <<'ENVEOF'
# === 必填 ===
DOMAIN=your-domain.com
DB_PASSWORD=                        # 強密碼（隨機 32 字元）
SECRET_KEY=                         # 強密碼（隨機 64 字元）

# === Email 週報（選填）===
RESEND_API_KEY=
EMAIL_FROM=report@your-domain.com
TLS_EMAIL=you@gmail.com             # Let's Encrypt 通知用

# === 生產環境 ===
APP_ENV=production
ENVEOF
        warn "請編輯 $APP_DIR/.env 填入必要設定，完成後再次執行 deploy.sh"
        echo ""
        echo "  nano $APP_DIR/.env"
        echo ""
        exit 0
    fi

    # 5. 確認 .env 必填欄位
    source "$APP_DIR/.env"
    [ -z "${DOMAIN:-}" ]      && die ".env 缺少 DOMAIN"
    [ -z "${DB_PASSWORD:-}" ] && die ".env 缺少 DB_PASSWORD"
    [ -z "${SECRET_KEY:-}" ]  && die ".env 缺少 SECRET_KEY"

    ok "初始化完成，繼續執行部署..."
    deploy
}

# ── 日常更新部署 ─────────────────────────────────────────
deploy() {
    cd "$APP_DIR"

    log "拉取最新程式碼..."
    git pull

    log "重新建置並啟動服務..."
    docker compose -f "$COMPOSE_FILE" build --pull
    docker compose -f "$COMPOSE_FILE" up -d --remove-orphans

    log "等待資料庫健康..."
    for i in $(seq 1 30); do
        if docker compose -f "$COMPOSE_FILE" exec -T postgres \
            pg_isready -U stockradar -q 2>/dev/null; then
            ok "資料庫就緒"
            break
        fi
        [ "$i" -eq 30 ] && die "資料庫 30 秒後仍未就緒"
        sleep 2
    done

    log "確認服務狀態..."
    docker compose -f "$COMPOSE_FILE" ps

    ok "部署完成 ✅"
    echo ""
    echo "  網站：https://$(grep DOMAIN .env | cut -d= -f2)"
    echo "  API：https://$(grep DOMAIN .env | cut -d= -f2)/api/health"
    echo ""
    echo "  查看 log：docker compose -f $COMPOSE_FILE logs -f"
    echo "  手動跑選股：docker compose -f $COMPOSE_FILE exec scheduler sh /app/scripts/run_now.sh"
}

# ── 入口 ─────────────────────────────────────────────────
case "${1:-}" in
    --init) init ;;
    *)      deploy ;;
esac
