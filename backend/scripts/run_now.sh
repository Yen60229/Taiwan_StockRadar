#!/bin/sh
# StockRadar - 即時手動執行
# 用法：bash scripts/run_now.sh
set -e
cd "$(dirname "$0")/.."
echo "🚀 StockRadar 手動執行 — $(date '+%Y-%m-%d %H:%M:%S')"
mkdir -p logs
LOG="logs/manual_$(date '+%Y%m%d_%H%M%S').log"

echo "📊 Step 1/2: 執行資料 Pipeline..."
python -m pipeline.data_pipeline 2>&1 | tee "$LOG"

echo "📧 Step 2/2: 寄送 Email 週報..."
python -m notifier.send_email 2>&1 | tee -a "$LOG"

echo "✅ 完成！日誌：$LOG"
