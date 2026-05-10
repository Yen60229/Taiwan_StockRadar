#!/bin/sh
# StockRadar - 非交易日手動執行（週末 / 假日）
# 用法：docker exec <scheduler> sh /app/scripts/run_offline.sh
# 功能：
#   - 不抓當日行情（市場休市）
#   - 從 DB 取最後一個交易日行情 + 20 日均量
#   - 重新抓集保籌碼（週四更新）+ HiStock 外資/董監持股
#   - 寫回 DB → /api/screen 自動反映

set -e
cd "$(dirname "$0")/.."
echo "🌙 StockRadar 非交易日模式 — $(date '+%Y-%m-%d %H:%M:%S')"
mkdir -p logs
LOG="logs/offline_$(date '+%Y%m%d_%H%M%S').log"

{
  echo "════════════════════════════════"
  echo "🌙 非交易日 Pipeline 開始 $(date '+%Y-%m-%d %H:%M:%S')"
  echo "════════════════════════════════"

  python -m pipeline.data_pipeline offline

  echo "✅ 非交易日 Pipeline 結束 $(date '+%Y-%m-%d %H:%M:%S')"
} 2>&1 | tee -a "$LOG"

echo "📋 日誌：$LOG"
