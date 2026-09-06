#!/bin/bash
# StockRadar — 還原演練（ADR-10：沒演練過的備份等於沒有備份）
#
# 用法：bash /opt/stockradar/scripts/restore_drill.sh [dump 檔路徑]
#       不指定就用 /opt/backups 裡最新的一份。
#
# 做什麼：
#   1. 起一個「拋棄式」的 PostgreSQL 容器（不碰 production DB）
#   2. 把 dump 還原進去
#   3. 逐表比對 row count 與最新日期，production vs 還原結果
#   4. 收掉臨時容器，印出實測 RTO
#
# 這支腳本是唯一能證明「備份可用」的東西。每季至少跑一次。

set -euo pipefail

APP_DIR="${APP_DIR:-/opt/stockradar}"
BACKUP_DIR="${BACKUP_DIR:-/opt/backups}"
COMPOSE_FILE="docker-compose.prod.yml"
TMP_CONTAINER="stockradar-restore-drill"
TMP_PW="drill-only-not-a-secret"

log() { echo "[$(date '+%H:%M:%S')] $*"; }
die() { echo "ERROR: $*" >&2; cleanup; exit 1; }
cleanup() { docker rm -f "$TMP_CONTAINER" >/dev/null 2>&1 || true; }
trap cleanup EXIT

cd "$APP_DIR" || die "找不到 $APP_DIR"

DUMP="${1:-$(find "$BACKUP_DIR" -maxdepth 1 -name 'stockradar_*.dump' | sort | tail -1)}"
[ -n "$DUMP" ] && [ -f "$DUMP" ] || die "找不到備份檔（$BACKUP_DIR 是空的？先跑 backup_db.sh）"

log "演練用備份：$DUMP（$(du -h "$DUMP" | cut -f1)）"
START=$(date +%s)

# ── 1. 起臨時 PostgreSQL ──────────────────────────────────────
PG_IMAGE=$(docker compose -f "$COMPOSE_FILE" config --images | grep -m1 postgres || echo "postgres:16-alpine")
log "啟動臨時容器（$PG_IMAGE）..."
cleanup
docker run -d --name "$TMP_CONTAINER" \
    -e POSTGRES_USER=stockradar \
    -e POSTGRES_PASSWORD="$TMP_PW" \
    -e POSTGRES_DB=stockradar \
    "$PG_IMAGE" >/dev/null

for i in $(seq 1 30); do
    docker exec "$TMP_CONTAINER" pg_isready -U stockradar -q 2>/dev/null && break
    [ "$i" -eq 30 ] && die "臨時資料庫 60 秒內沒起來"
    sleep 2
done
log "臨時資料庫就緒"

# ── 2. 還原 ───────────────────────────────────────────────────
log "還原中..."
docker exec -i "$TMP_CONTAINER" pg_restore -U stockradar -d stockradar --no-owner < "$DUMP" \
    || log "pg_restore 有非致命警告（常見於 extension / owner），繼續比對"

END=$(date +%s)
RTO=$((END - START))

# ── 3. 比對 production vs 還原結果 ────────────────────────────
QUERY="SELECT 'stocks' t, COUNT(*)::text n, '' d FROM stocks
UNION ALL SELECT 'daily_quotes', COUNT(*)::text, COALESCE(MAX(trade_date)::text,'-') FROM daily_quotes
UNION ALL SELECT 'institutional_flow', COUNT(*)::text, COALESCE(MAX(trade_date)::text,'-') FROM institutional_flow
UNION ALL SELECT 'chip_concentration', COUNT(*)::text, COALESCE(MAX(week_date)::text,'-') FROM chip_concentration
UNION ALL SELECT 'ownership_ratios', COUNT(*)::text, COALESCE(MAX(report_date)::text,'-') FROM ownership_ratios
UNION ALL SELECT 'users', COUNT(*)::text, '' FROM users
UNION ALL SELECT 'watchlist', COUNT(*)::text, '' FROM watchlist
ORDER BY 1;"

log "比對 production 與還原結果..."
PROD=$(docker compose -f "$COMPOSE_FILE" exec -T postgres \
        psql -U stockradar -d stockradar -At -F'|' -c "$QUERY")
REST=$(docker exec -i "$TMP_CONTAINER" \
        psql -U stockradar -d stockradar -At -F'|' -c "$QUERY")

echo
printf '%-20s %12s %12s   %s\n' "TABLE" "PRODUCTION" "RESTORED" "STATUS"
printf '%s\n' "--------------------------------------------------------------------"
FAIL=0
while IFS='|' read -r t n d; do
    rline=$(printf '%s\n' "$REST" | grep "^${t}|" || true)
    rn=$(printf '%s' "$rline" | cut -d'|' -f2)
    rd=$(printf '%s' "$rline" | cut -d'|' -f3)
    if [ "$n" = "$rn" ] && [ "$d" = "$rd" ]; then
        status="OK"
    else
        status="MISMATCH (date $d vs $rd)"; FAIL=1
    fi
    printf '%-20s %12s %12s   %s\n' "$t" "$n" "${rn:-—}" "$status"
done <<< "$PROD"
echo

if [ "$FAIL" -eq 0 ]; then
    log "✅ 演練通過 — 備份可還原，所有資料表 row count 與最新日期一致"
    log "   實測 RTO：${RTO} 秒（從零到資料可用）"
    log "   請把日期與 RTO 記到 docs/backup-restore.md 的演練記錄"
else
    log "❌ 演練失敗 — 有資料表對不上，這份備份不可信，請調查後重跑"
    exit 1
fi
