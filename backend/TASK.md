# StockRadar 週報任務

## 目標
自動更新台股資料並產出篩選清單：
  ・平日 18:00 — 盤後更新全部個股的成交量、20 日均量、三大法人買賣超
  ・週六 10:00 — 完整 pipeline（＋集保籌碼、持股比例）並寄送 Email 週報
  ・週日 10:00 — 完整 pipeline 補跑（不重複寄信）

## 環境確認
執行前請確認以下環境變數已設定：
- ANTHROPIC_API_KEY
- DATABASE_URL
- RESEND_API_KEY

## 篩選條件
- 日均成交量（近20交易日平均）>= 2,000 張
- 籌碼集中度（集保400張以上持股人數比例）>= 40%
- 同時包含上市（TWSE）與上櫃（TPEX）股票

## 執行步驟

### Step 1：確認環境
```bash
cd /home/stockradar/app/backend
source .env
python -c "from models.database import engine; print('DB OK')"
```

### Step 2：執行完整 Pipeline
```bash
python -m pipeline.data_pipeline
```
若執行成功，logs/ 目錄下會產生當日 run log。

### Step 3：寄送 Email 週報
```bash
python -m notifier.send_email
```

### Step 4：確認完成
檢查 logs/run_$(date +%Y%m%d).log 最後一行是否包含「✅ Pipeline 完成」與「Email 發送成功」。

## 錯誤處理原則
1. 若 Step 2 失敗：
   - 讀取錯誤訊息
   - 若是網路錯誤（timeout/connection），等待 60 秒後重試
   - 若是 HTML 解析錯誤（集保結構可能改版），讀取 scraper/tdcc_scraper.py，
     分析新的 HTML 結構，修正 parse_holding_table() 函數後重試
   - 若是 DB 連線錯誤，確認 DATABASE_URL 環境變數後重試
   - 最多重試 3 次，超過則寄送錯誤通知

2. 若 Step 3 失敗：
   - 確認 RESEND_API_KEY 是否有效
   - 改用 SMTP 備援（smtp.gmail.com）

3. 所有重試失敗後：
   - 寄送錯誤通知給 EMAIL_ADMIN
   - 在 logs/ 記錄完整錯誤訊息

## 完成標準
- logs/run_YYYYMMDD.log 存在且包含「✅ Pipeline 完成」
- Email 已成功發送（Resend API 回傳 200）
- 執行總時間不超過 3 小時
