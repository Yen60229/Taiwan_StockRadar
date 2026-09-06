# 接續開發步驟（Ampere VM 到手後的第一個月）

> 這份是「現在該做什麼」的短清單，補在 1–2 年藍圖前面。
> 每一步只講做什麼、為什麼、去哪裡學；細節自己查得到就不寫。
> 順序就是優先序：**先上線 → 補資料缺口 → 加融資副圖 → 接回藍圖 Phase 1**。

---

## Step 1｜把 StockRadar 搬上 Ampere（目標：1–2 週）

搶到的規格是 **2 OCPU / 12 GB ARM**，跑 Docker 完全夠。

| # | 做什麼 | 為什麼 / 注意 |
|---|---|---|
| 1 | SSH 進新 VM（同一把 ssh key） | Oracle Console → Compute → Instances 看 Public IP |
| 2 | 裝 Docker + compose plugin，`usermod -aG docker ubuntu` | 官方 convenience script 一行搞定 |
| 3 | **開 80/443 兩道門**：① Console VCN → Security List 加 Ingress 80/443；② VM 內 `iptables -I INPUT 6 -m state --state NEW -p tcp --dport 80 -j ACCEPT`（443 同）+ `netfilter-persistent save` | Oracle 的 Ubuntu image 內建 iptables 會擋 80/443，**只開 Console 沒用**——這是最多人卡住的坑 |
| 4 | 弄一個網域，A record 指到 VM IP | Caddy 要有網域才能自動拿 HTTPS 憑證；免費用 DuckDNS，便宜買用 Cloudflare |
| 5 | `git clone` → 建 `.env`（DOMAIN / DB_PASSWORD / SECRET_KEY / TLS_EMAIL） | `.env` 永遠不進 git |
| 6 | **第一次手動建表**：`docker compose -f docker-compose.prod.yml run --rm api python -c "import asyncio; from models.database import init_db; asyncio.run(init_db())"` | `APP_ENV=production` 時程式會跳過 `init_db()`，不做這步 API 一啟動就炸。正解是 Alembic（藍圖 Phase 1） |
| 7 | `docker compose -f docker-compose.prod.yml up -d --build` | 用的 base image（python-slim / node-alpine / postgres-alpine / caddy）都有 arm64 版，不用改 |
| 8 | `backfill_history.py` → `run_now.sh` | 先補 2 個月歷史讓 20 日均量準，再跑當日 |
| 9 | 驗收：瀏覽器開 `https://你的網域`、`/api/screen` 有資料、`docker compose ps` 全 Up | |
| 10 | 收尾：搶機用的跳板 VM 可留（不花錢）或刪；把 `docs/oracle-cloud-automation.md` 裡的真實 IP / Gmail 清掉 | 公開 repo 不放個資 |

**上線後第一個週末要確認**：週六 08:00 的排程是否真的寫入 DB（查 `daily_quotes` 的 `max(trade_date)`）。藍圖 P0-1 指出 scheduler 的 cron 拿不到環境變數，**很可能會失敗**——沒寫入就先修那個 bug（見 Step 4）。

**學習資源**
- Docker 安裝：docs.docker.com/engine/install/ubuntu
- Oracle 開 port：搜「oracle cloud ubuntu iptables port 80」，任一篇都會講到 `iptables -I INPUT 6`
- Caddy 自動 HTTPS：caddyserver.com/docs/getting-started（10 分鐘讀完）
- 免費網域：duckdns.org

---

## Step 2｜補「外資 / 投信」資料缺口

先講診斷結果（2026-08-01 的 pipeline log 已確認）：

| 項目 | 現況 | 結論 |
|---|---|---|
| 外資 / 投信**買賣超** | DB 有（TWSE 1085 筆 + TPEX 794 筆）、API 有回傳 | **前端 Dashboard 根本沒放這兩欄**，個股頁的 30 日折線圖才有 → 加欄位就好 |
| 外資**持股比例** | 走 HiStock 每週資料，591 筆有寫入 | 值是否為空要開 Docker 查（SQL 在下面）。長期建議換成證交所每日資料 |
| 投信**持股比例** | 程式註解寫明「無可靠來源，維持 NULL」 | **不是 bug，是沒做**。目前沒有官方每日投信持股表 |

```sql
-- Docker 開著時執行，確認外資持股有沒有值
SELECT COUNT(*) total,
       COUNT(foreign_hold_ratio)  has_foreign,
       COUNT(director_hold_ratio) has_director,
       MAX(report_date)           latest
FROM ownership_ratios;
```

**要做的三件事（由易到難）**
1. **Dashboard 加「外資買賣超 / 投信買賣超」兩欄**：`frontend/src/pages/DashboardPage.tsx` 的 `columns` 陣列加兩筆（key = `foreign_net` / `trust_net`，單位張，正綠負紅），資料已經在 `ScreenItem` 裡。半天。
2. **外資持股改用證交所每日資料**：TWSE「外資及陸資投資持股統計」有 JSON（報表代號 `MI_QFIIS`，每日、每檔都有持有股數與持股比率），比 HiStock 每週一筆穩定、也不怕被擋。新開一個 scraper，寫進 `ownership_ratios`（或另開每日表）。1–2 天。
3. **投信持股**：兩條路——(a) 用「投信買賣超累計」推估，畫面標明是估算；(b) 直接用 FinMind API（免費、有現成資料集，一次解決外資 / 投信 / 融資），少寫三支爬蟲。先做 (b) 試水溫最省力。

**學習資源**
- 證交所資料怎麼找：twse.com.tw「交易資訊」每張表右上角都有 JSON / CSV 連結，網址規則都是 `rwd/zh/<分類>/<報表代號>?date=YYYYMMDD&response=json`
- FinMind 文件：finmind.github.io/（資料集清單就是台股資料源地圖，即使不用它也值得看一遍）

---

## Step 3｜融資餘額副圖（搭配外資持股，像 KD / MACD）

**想達成的畫面**（個股頁）
```
┌ 主圖：收盤價（90 日）──────────────────────┐
├ 副圖 1：三大法人買賣超（已有）────────────────┤
├ 副圖 2：融資餘額（柱，左軸 張）＋ 外資持股率（線，右軸 %）┤
└─────────────────────────────────────────────┘
```

**分三塊做**

| 塊 | 內容 | 工具 |
|---|---|---|
| 資料 | 新 scraper：TWSE「融資融券彙總」JSON（報表代號 `MI_MARGN`，每日每檔：融資買進 / 賣出 / 現償 / **餘額**、融券同）；TPEX 在 openapi 清單搜「margin」確認端點 | 照 `twse_scraper.fetch_institutional_flow` 的寫法抄 |
| 儲存 | 新表 `margin_balance(stock_code, trade_date, margin_balance, margin_change, short_balance, short_change)` + `UNIQUE(stock_code, trade_date)` | 照 `institutional_flow` 的 model 抄 |
| 畫面 | `/api/stocks/{code}` 多回 `closes_90d` 與 `margin_90d`；StockPage 用 recharts **`ComposedChart`** + 兩個 `YAxis`（`yAxisId="left"` 張、`"right"` %） | recharts 已裝，不用加套件 |

**兩個要先想清楚的點**
- **時間粒度要一致**：融資餘額是每日，外資持股若還是 HiStock 每週一筆，副圖會變成階梯線很難看 → 所以 Step 2 的第 2 件事（改每日）要先做。
- **主圖現在不存在**：StockPage 只有法人折線圖，沒有價格圖。要有「副圖」概念得先補主圖（收盤價 `daily_quotes` 已經在 DB，只差 API 回傳）。

**學習資源**
- recharts 雙軸範例：recharts.org/en-US/examples/LineBarAreaComposedChart（直接改 dataKey 就能用）
- 融資融券怎麼解讀：證交所「融資融券說明」看定義；財報狗 / 玩股網教學文看常見判讀（融資餘額與外資持股走勢背離等）

---

## Step 4｜接回 1–2 年藍圖 Phase 1

上面三步做完，回到 `01-backend.md` / `03-cloud-devops.md` 的 Phase 1。**跟「已上線」最直接相關、建議最先修的三個 P0**：

1. **scheduler cron 拿不到環境變數**（P0-1）——不修，週末自動排程等於沒有；`cron_entry.sh` 開頭 `printenv | grep -E 'DATABASE_URL|RESEND|SMTP|EMAIL' > /etc/environment` 是最小修法
2. **非交易日 `date.today()` 污染時序表**（P0-2）——改用 API 回傳的交易日期
3. **`SECRET_KEY` 有 `change-me` fallback**（P0-3）——沒設就拒絕啟動

然後才是 Alembic、pytest、CI、備份——順序照藍圖走，不要跳。

---

## 一頁總覽

```
Week 1–2   上線 Ampere（Docker / 開 port / 網域 / Caddy / 建表 / backfill）
Week 3     Dashboard 加買賣超欄位 → 外資持股改證交所每日 → 投信持股（FinMind 試水）
Week 4–5   融資餘額 scraper + 表 + 個股頁主圖 / 副圖
Week 6+    藍圖 Phase 1 P0（cron env / 交易日 / SECRET_KEY）→ Alembic → pytest → CI → 備份
```

*建立：2026-08*
