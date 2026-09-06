#!/bin/bash
# StockRadar — 交易日盤後更新（每個交易日執行）
#
# 更新：當日行情 + 三大法人買賣超 + 重算 20 日均量
# 不做：TDCC 集保籌碼、HiStock 持股比例（週更資料，週末的 run_scheduled.sh 負責）
#       也不寄信 —— 週報一週一次就好
#
# 約 1–3 分鐘。非交易日跑到也安全：行情 API 回最近交易日快照，
# trade_date 取自 payload，等於把同一天再 upsert 一次（冪等）。

set -euo pipefail

# cron job 拿不到容器環境變數，由 cron_entry.sh 匯出到這個檔案
[ -f /etc/stockradar.env ] && . /etc/stockradar.env

cd /app
mkdir -p logs
LOG="logs/daily_$(date '+%Y%m%d').log"

{
  echo "════════════════════════════════"
  echo "📈 交易日行情更新 $(date '+%Y-%m-%d %H:%M:%S')"
  echo "════════════════════════════════"
} >> "$LOG"

# pipefail 讓 python 的失敗不會被 tee 吃掉（exit code 要能傳給 cron）
set -o pipefail
if python -m pipeline.data_pipeline quotes 2>&1 | tee -a "$LOG"; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ✅ 完成" | tee -a "$LOG"
else
    rc=$?
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ❌ 失敗（exit=$rc）" | tee -a "$LOG"
    exit "$rc"
fi
