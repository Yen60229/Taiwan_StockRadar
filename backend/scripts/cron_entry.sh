#!/bin/sh
# Scheduler container 啟動：寫入 crontab，啟動 cron daemon
set -e
mkdir -p /app/logs

# crontab：每週六 / 週日 08:00 執行
cat > /etc/cron.d/stockradar <<'EOF'
SHELL=/bin/sh
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
TZ=Asia/Taipei

# 週六 08:00
0 8 * * 6 root sh /app/scripts/run_scheduled.sh
# 週日 08:00
0 8 * * 0 root sh /app/scripts/run_scheduled.sh
EOF

chmod 0644 /etc/cron.d/stockradar
crontab /etc/cron.d/stockradar

echo "🕐 cron 已啟動，下次執行時間："
echo "  - 每週六 08:00 (Asia/Taipei)"
echo "  - 每週日 08:00 (Asia/Taipei)"
echo "📋 手動執行：docker-compose exec scheduler sh /app/scripts/run_now.sh"

# 前景執行 cron + tail log
cron -f &
CRON_PID=$!
touch /app/logs/scheduled_keep_alive.log
tail -F /app/logs/scheduled_*.log 2>/dev/null &
wait $CRON_PID
