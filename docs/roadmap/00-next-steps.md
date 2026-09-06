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
| 3 | **開 80/443**：Console VCN → Security List 加 Ingress 80/443（**必做**）。VM 內的 iptables 通常不用動——Docker 發布的 port 走 DOCKER chain，會繞過 Oracle image 預設的 INPUT REJECT 規則；若開完 Security List 仍不通，再補 `iptables -I INPUT 6 -m state --state NEW -p tcp --dport 80 -j ACCEPT`（443 同）+ `netfilter-persistent save` | 最多人卡在忘了開 Security List |
| 4 | 弄一個網域，A record 指到 VM IP | Caddy 要有網域才能自動拿 HTTPS 憑證；免費用 DuckDNS，便宜買用 Cloudflare |
| 5 | `git clone` → 建 `.env`（DOMAIN / DB_PASSWORD / SECRET_KEY / TLS_EMAIL） | `.env` 永遠不進 git |
| 6 | `bash scripts/deploy.sh --init`（第一次）→ 填 `.env` → 再跑一次 | 會 build、啟動、等 DB 就緒、**自動建表**（prod 不會自己 create_all）。base image 都有 arm64 版，不用改 |
| 7 | `docker compose -f docker-compose.prod.yml exec api python scripts/backfill_history.py` | 先補 2 個月歷史讓 20 日均量準 |
| 8 | 跑一次清理 SQL（`05-review-2026-09.md` 附錄）→ `SKIP_EMAIL=1 sh scripts/run_now.sh` | 先清掉舊的週末污染列，再跑當日；測試跑加 `SKIP_EMAIL=1` 才不會寄週報給訂閱者 |
| 9 | 驗收：瀏覽器開 `https://你的網域`、`/api/screen` 有資料、`docker compose ps` 全 Up | |
| 10 | 收尾：搶機用的跳板 VM 可留（不花錢）或刪；把 `docs/oracle-cloud-automation.md` 裡的真實 IP / Gmail 清掉 | 公開 repo 不放個資 |

**上線後要確認的排程**（P0-1 cron 環境變數與 P0-2 週末日期都已修，這是驗收）：
- 平日 18:00 的 `run_daily.sh` 有更新當日行情與法人（查 `daily_quotes` 的 `max(trade_date)`）
- 週六 10:00 的完整 pipeline 有寫入籌碼，且 `max(trade_date)` 是**週五**不是週六

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

P0-1（cron 環境變數）、P0-2（週末日期）、P0-3（SECRET_KEY）、P0-4（prod 建表）、P0-5（race / UUID / bcrypt）、P0-7（bind mount / root / port）**已在 2026-09 的 Batch A 修掉**（見 `05-review-2026-09.md`）。剩下照藍圖順序：

1. pytest 地基 + GitHub Actions CI（P0-6）→ 之後才換 python-jose → PyJWT（ADR-11）
2. Alembic baseline，`deploy.sh` 改 `alembic upgrade head`
3. 備份 + 一次 restore 演練（P0-8，ADR-10 上線 gate）
4. Oracle 帳戶升級 Pay-As-You-Go 或明確接受 idle reclaim 風險（藍圖漏掉的）

---

## 一頁總覽

```
Week 1–2   上線 Ampere（Docker / 開 port / 網域 / Caddy / 建表 / backfill）
Week 3     Dashboard 加買賣超欄位 → 外資持股改證交所每日 → 投信持股（FinMind 試水）
Week 4–5   融資餘額 scraper + 表 + 個股頁主圖 / 副圖
Week 6+    藍圖 Phase 1 剩餘：pytest + CI → PyJWT → Alembic → 備份/restore 演練
```

*建立：2026-08*
