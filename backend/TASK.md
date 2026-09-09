# StockRadar 排程任務

## 目標
自動更新台股資料並產出篩選清單：
  ・平日 18:00 — 盤後更新全部個股的成交量、20 日均量、三大法人買賣超
  ・週六 10:00 — 完整 pipeline（＋集保籌碼、持股比例）並寄送 Email 週報
  ・週日 10:00 — 完整 pipeline 補跑（不重複寄信）

排程本身寫在 `scripts/cron_entry.sh`，由 scheduler container 內的 cron 執行，
時區是 Asia/Taipei。宿主機的 crontab 只有備份，不要在那裡找排程。

## 環境確認
執行前請確認以下環境變數已設定：
- `DATABASE_URL`
- `SECRET_KEY`
- `RESEND_API_KEY` 或 `SMTP_USER` / `SMTP_PASS`（要寄信才需要）

cron 不會繼承 daemon 的環境變數，所以 `cron_entry.sh` 會先把這些寫進
`/etc/stockradar.env`，各 `run_*.sh` 開頭再 source 它。

## 篩選條件
- 日均成交量（近 20 交易日平均）>= 2,000 張
- 籌碼集中度（集保 400 張以上持股人數比例）>= 40%
- 同時包含上市（TWSE）與上櫃（TPEX）股票

## 手動執行

```bash
# 當日行情 + 法人（平日 18:00 排程做的事）
docker compose -f docker-compose.prod.yml exec scheduler bash /app/scripts/run_daily.sh

# 完整 pipeline（測試時加 SKIP_EMAIL=1，免得寄信給訂閱者）
docker compose -f docker-compose.prod.yml exec -e SKIP_EMAIL=1 scheduler sh /app/scripts/run_now.sh

# 補某一天的上市行情與法人（排程沒跑成功、或資料有洞時）
docker compose -f docker-compose.prod.yml exec scheduler python -m scripts.backfill_twse_day 2026-09-09
```

log 在 container 內的 `/app/logs/`，檔名是 `daily_YYYYMMDD.log`／`scheduled_*.log`。

## 確認執行結果

```bash
docker compose -f docker-compose.prod.yml exec scheduler sh -c 'tail -20 /app/logs/daily_$(date +%Y%m%d).log'
```

最後一行要有「✅ 完成」。另外檢查兩市的交易日有沒有對齊：

```sql
SELECT s.market, MAX(dq.trade_date)
FROM daily_quotes dq JOIN stocks s ON s.code = dq.stock_code
GROUP BY s.market;
```

TWSE 與 TPEX 應該是同一天。log 裡出現「TWSE 與 TPEX 交易日不一致」的
WARNING 就是有一邊的資料沒跟上，要去查那一邊的來源。

## 錯誤處理原則

1. pipeline 失敗：
   - 網路錯誤（timeout / connection）→ 等 60 秒重試，最多 3 次
   - HTML 解析錯誤 → 集保網頁可能改版，看 `scraper/tdcc_scraper.py` 的
     `parse_holding_table()`
   - DB 連線錯誤 → 確認 `DATABASE_URL`

2. 寄信失敗：
   - 確認 `RESEND_API_KEY` 是否有效，或改用 SMTP（`SMTP_USER` / `SMTP_PASS`）
   - 注意：帳號通知信刻意設計成「寄不出去也不會讓核准失敗」，
     只會在 log 留一筆 WARNING，不要以為沒噴錯就是寄成功了

3. 都失敗：寄錯誤通知給 `EMAIL_ADMIN`，並在 log 記完整錯誤訊息
