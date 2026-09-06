#!/bin/sh
# StockRadar - 排程執行（cron / scheduler container 用）
set -e
# cron job 拿不到容器環境變數（P0-1）：由 cron_entry.sh 匯出到這個檔案
[ -f /etc/stockradar.env ] && . /etc/stockradar.env
cd /app
mkdir -p logs
LOG="logs/scheduled_$(date '+%Y%m%d').log"

{
  echo "════════════════════════════════"
  echo "🕐 排程啟動 $(date '+%Y-%m-%d %H:%M:%S')"
  echo "════════════════════════════════"

  # Pipeline 重試 3 次
  for i in 1 2 3; do
    echo "📊 嘗試 $i/3：執行 Pipeline"
    if python -m pipeline.data_pipeline; then
      echo "✅ Pipeline 成功"
      break
    fi
    echo "⚠️  Pipeline 失敗，等待 60 秒重試..."
    sleep 60
  done

  echo "📧 寄送週報"
  python -m notifier.send_email || echo "⚠️ Email 發送失敗"

  echo "✅ 排程結束 $(date '+%Y-%m-%d %H:%M:%S')"
} 2>&1 | tee -a "$LOG"
