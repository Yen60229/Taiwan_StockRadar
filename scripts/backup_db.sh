#!/bin/bash
# StockRadar — 每日資料庫備份
#
# 用法：
#   手動：bash /opt/stockradar/scripts/backup_db.sh
#   排程：host crontab（見 docs/backup-restore.md）
#
# 產出：/opt/backups/stockradar_YYYYmmdd_HHMMSS.dump（pg_dump 自訂格式，已壓縮）
# 保留：預設 14 天，可用 RETENTION_DAYS 覆寫
#
# ⚠️ 這份備份跟資料庫在同一台機器上，只能防「誤刪 / 誤改」，
#    防不了「機器整台不見」（Oracle 回收實例、磁碟故障）。
#    異地複本是下一步，見 docs/backup-restore.md。

set -euo pipefail

APP_DIR="${APP_DIR:-/opt/stockradar}"
BACKUP_DIR="${BACKUP_DIR:-/opt/backups}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"
COMPOSE_FILE="docker-compose.prod.yml"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }
die() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] ERROR: $*" >&2; exit 1; }

cd "$APP_DIR" || die "找不到 $APP_DIR"
mkdir -p "$BACKUP_DIR"

TS="$(date '+%Y%m%d_%H%M%S')"
OUT="$BACKUP_DIR/stockradar_${TS}.dump"

log "開始備份 → $OUT"

# -Fc = custom format（已壓縮、可選擇性還原）；-T 避免 TTY 破壞二進位輸出
if ! docker compose -f "$COMPOSE_FILE" exec -T postgres \
        pg_dump -U stockradar -Fc stockradar > "$OUT"; then
    rm -f "$OUT"
    die "pg_dump 失敗"
fi

# ── 驗證這個 dump 真的讀得回來（不是只有檔案存在）─────────────
SIZE=$(stat -c%s "$OUT")
[ "$SIZE" -gt 10240 ] || { rm -f "$OUT"; die "dump 只有 ${SIZE} bytes，明顯不完整"; }

if ! docker compose -f "$COMPOSE_FILE" exec -T postgres pg_restore -l - < "$OUT" > /dev/null 2>&1; then
    rm -f "$OUT"
    die "dump 無法被 pg_restore 讀取，已刪除"
fi

log "備份完成：$(du -h "$OUT" | cut -f1)"

# ── 清掉超過保留期的舊備份 ────────────────────────────────────
DELETED=$(find "$BACKUP_DIR" -maxdepth 1 -name 'stockradar_*.dump' \
            -mtime "+$RETENTION_DAYS" -print -delete | wc -l)
[ "$DELETED" -gt 0 ] && log "清除 $DELETED 個超過 ${RETENTION_DAYS} 天的舊備份"

log "目前保有 $(find "$BACKUP_DIR" -maxdepth 1 -name 'stockradar_*.dump' | wc -l) 份備份，" \
    "共 $(du -sh "$BACKUP_DIR" | cut -f1)"
