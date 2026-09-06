#!/bin/sh
# Scheduler container 啟動：匯出環境變數給 cron job、寫入 cron.d、前景跑 cron daemon
set -e
mkdir -p /app/logs

# ── P0-1：Debian cron 不會把 daemon 的環境變數傳給 job ──────────
# 把容器拿到的環境變數以 shell 可安全 source 的格式寫到 /etc/stockradar.env，
# 各 run_*.sh 開頭會 source 它。
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

# ── 排程（Asia/Taipei）────────────────────────────────────────
#   平日 18:00  行情 + 三大法人 + 均量（快，約 1–3 分鐘）
#               18:00 是安全邊際：13:30 收盤、行情約 15:00 更新、T86 約 16:00 後公布
#   週六 08:00  完整 pipeline（TDCC 集保籌碼 + 持股比例）+ 寄週報
#   週日 08:00  完整 pipeline 補跑，SKIP_EMAIL=1 避免訂閱者一週收到兩封
#
# ⚠️ 不要再 `crontab /etc/cron.d/stockradar`：cron.d 格式含 user 欄位，
#    裝進 user crontab 會把 "root" 當指令執行，而且同一時間雙重觸發。
cat > /etc/cron.d/stockradar <<'EOF'
SHELL=/bin/sh
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
TZ=Asia/Taipei

0 18 * * 1-5 root bash /app/scripts/run_daily.sh
0 8 * * 6 root sh /app/scripts/run_scheduled.sh
0 8 * * 0 root SKIP_EMAIL=1 sh /app/scripts/run_scheduled.sh
EOF
chmod 0644 /etc/cron.d/stockradar

echo "🕐 cron 已啟動（Asia/Taipei）："
echo "   平日 18:00  行情 + 三大法人 + 均量"
echo "   週六 08:00  完整 pipeline + 週報"
echo "   週日 08:00  完整 pipeline（不寄信）"
echo "📋 手動執行："
echo "   行情：docker compose exec scheduler bash /app/scripts/run_daily.sh"
echo "   完整：docker compose exec -e SKIP_EMAIL=1 scheduler sh /app/scripts/run_now.sh"

# 前景執行 cron + tail log
cron -f &
CRON_PID=$!
touch /app/logs/scheduled_keep_alive.log
tail -F /app/logs/scheduled_*.log /app/logs/daily_*.log 2>/dev/null &
wait $CRON_PID
