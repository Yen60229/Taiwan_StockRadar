#!/bin/sh
# Scheduler container 啟動：匯出環境變數給 cron job、寫入 cron.d、前景跑 cron daemon
set -e
mkdir -p /app/logs

# ── P0-1：Debian cron 不會把 daemon 的環境變數傳給 job ──────────
# 把容器拿到的環境變數以 shell 可安全 source 的格式寫到 /etc/stockradar.env，
# run_scheduled.sh 開頭會 source 它。
# 放 /etc 而非 /app：dev 的 bind mount 會把 /app 底下的檔案寫回宿主機。
python3 - <<'PY'
import os, shlex
KEYS = [
    "DATABASE_URL", "SECRET_KEY", "APP_ENV", "TZ", "PYTHONPATH",
    "RESEND_API_KEY", "EMAIL_FROM", "EMAIL_ADMIN", "SMTP_USER", "SMTP_PASS",
    "MIN_AVG_VOL", "MIN_CHIP_CONC", "TDCC_REQUEST_DELAY",
]
with open("/etc/stockradar.env", "w") as f:
    for k in KEYS:
        v = os.environ.get(k)
        if v is not None:
            f.write(f"export {k}={shlex.quote(v)}\n")
PY
chmod 600 /etc/stockradar.env

# ── crontab：每週六 / 週日 08:00 (Asia/Taipei) ───────────────────
# 只放 /etc/cron.d（系統格式，含 user 欄位）。
# ⚠️ 不要再 `crontab /etc/cron.d/stockradar`：user crontab 沒有 user 欄位，
#    會把 "root" 當成指令執行，而且同一時間會雙重觸發。
cat > /etc/cron.d/stockradar <<'EOF'
SHELL=/bin/sh
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
TZ=Asia/Taipei

0 8 * * 6 root sh /app/scripts/run_scheduled.sh
0 8 * * 0 root sh /app/scripts/run_scheduled.sh
EOF
chmod 0644 /etc/cron.d/stockradar

echo "🕐 cron 已啟動，排程：每週六、週日 08:00 (Asia/Taipei)"
echo "📋 手動執行：docker compose exec scheduler sh /app/scripts/run_now.sh"

# 前景執行 cron + tail log
cron -f &
CRON_PID=$!
touch /app/logs/scheduled_keep_alive.log
tail -F /app/logs/scheduled_*.log 2>/dev/null &
wait $CRON_PID
