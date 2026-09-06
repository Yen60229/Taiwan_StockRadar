# StockRadar 1–2 年中長期發展藍圖(總覽)

> 制定日期:2026-07-07 · 適用對象:solo 開發者、每週可投入 **8–12 小時(三軌共用同一時間池)**
> 制定方法:4 個面向的完整程式碼審視 → 三軌路線圖獨立起草 → 跨軌矛盾審查(21 條修正)→ 整合決議

## 文件結構

| 文件 | 內容 |
|---|---|
| [`00-next-steps.md`](./00-next-steps.md) | **先讀這份**:Ampere VM 到手後第一個月的接續步驟(上線 → 補外資/投信資料 → 融資餘額副圖 → 接回 Phase 1) |
| **本文件** | 願景、現況評估、整合時間表、跨軌決議(ADR)、合規與產品補強、icebox |
| [`01-backend.md`](./01-backend.md) | 後端與資料工程路線圖(安全修復 → 測試/Migrations → API 強化 → 爬蟲可靠性 → 背景工作 → 進階功能) |
| [`02-frontend.md`](./02-frontend.md) | 前端路線圖(工程基線 → 表格重構/虛擬化 → Auth 安全 → 圖表/RWD/a11y → 產品化) |
| [`03-cloud-devops.md`](./03-cloud-devops.md) | 雲端架構與 DevOps 路線圖 + 學習地圖(VPS → CI/CD/備份/監控 → Terraform/Neon → Cloud Run) |
| [`04-critical-review.md`](./04-critical-review.md) | 21 條跨軌審查修正的完整原文(本文件 ADR 的依據) |

**衝突裁決順序:本文件的 ADR > 三份單軌文件。** 單軌文件內的工時估計是「單軌獨立」視角,實際排程一律以本文件的整合時間表為準。

---

## 1. 願景

把 StockRadar 從「本地 Docker 跑起來的個人工具」演進成:

1. **實用的產品**——有真實使用者每週主動打開,籌碼趨勢圖與警報是核心差異化。
2. **生產等級的系統**——有測試、CI/CD、備份演練、監控告警,連續數月無人工介入自動營運。
3. **雲原生架構**——無狀態 compute(Cloud Run)+ managed DB(Neon)+ 全 IaC(Terraform),月成本 < $20–30。
4. **一套完整的作品集敘事**——每個架構決策都能被面試官追問三層而不虛。

## 2. 現況評估摘要(2026-07)

完整分析見各單軌文件開頭。跨面向的關鍵結論:

**做得好的**:
- 全鏈路 async(FastAPI + asyncpg + httpx),screener 單一 multi-join 查詢、無 N+1;
- 時序表都有 `(stock_code, date)` unique constraint,upsert 冪等;
- bcrypt 密碼雜湊正確、JWT 有 pin algorithm、watchlist 無 IDOR、全面參數化查詢;
- 爬蟲有實戰工程判斷(CSRF token 處理、Big5 解碼、ISIN 繞路)。

**P0 風險(Phase 1 必修,詳見 `01-backend.md` / `03-cloud-devops.md`)**:

| # | 問題 | 影響 |
|---|---|---|
| 1 | scheduler cron 拿不到環境變數(Debian cron 不繼承 daemon env) | **排程實際上每次都失敗**,現有資料可能不完整 |
| 2 | 非交易日執行時以 `date.today()` 寫入 | 週末假資料污染時序表 |
| 3 | `SECRET_KEY` 有 `change-me-in-production` fallback | 環境變數未設時任何帳號可被偽造 |
| 4 | production 無任何建表路徑(`init_db()` 在 prod 被跳過、無 Alembic) | 上線即卡死 |
| 5 | 偽造 token 觸發 500(`UUID()` ValueError 未捕捉)、註冊 race condition、python-jose CVE | 安全與穩定性 |
| 6 | 零測試、無 lockfile、無 CI | 任何修改都不可驗證 |
| 7 | prod compose 掛 bind mount、容器跑 root、dev compose 5432/8000 全網暴露 | 部署安全 |
| 8 | 無備份 | 一次磁碟故障 = 專案歸零 |

## 3. 核心原則

1. **正確性 > 可靠性 > 效能 > 功能**。P0 的排程與日期 bug 意味著現在累積的資料可能是壞的——任何新功能都建立在錯誤資料上,先止血。
2. **三軌共用一個時間池**。三份單軌文件各自假設每週 6–12h,加總是不存在的 20–32h;實際以下方整合時間表的分配比例執行,做不完就往後推,不砍 Phase 1。
3. **每個修復配一個測試;每個 Phase 的測試投資是下個 Phase 敢大改的前提。**
4. **資料先於功能**。時序資料錯過就補不回來——盡早移除 scrape-time 過濾、盡早開始累積完整歷史。
5. **延遲決策要留紀錄**。TimescaleDB、Celery、Kubernetes 都是「現在不需要」;用 ADR 寫下觸發條件,而不是永遠不考慮。
6. **可持續性優先於進度**。每個 Phase 結尾做 30 分鐘 review(見 §7),避免 side project 最大的風險:棄坑。

## 4. 整合時間表(單一時間池,每週 8–12h)

| Phase | 期間 | 主題 | 時間分配 | 關鍵交付 |
|---|---|---|---|---|
| **1** | 0–3 月 | **止血與上線** | 後端 50% / 雲端 35% / 前端 15% | P0 全修、pytest 地基 + CI、Alembic、VPS 上線、每日備份 + **第一次 restore 演練(上線 gate)**、前端 lockfile/lint/auth 統一 |
| **2** | 3–6 月 | **可靠性與開放註冊** | 後端 40% / 前端 30% / 雲端 30% | 爬蟲驗證層 + pipeline_runs 稽核、rate limit、refresh token + email 驗證/忘記密碼/刪帳號、表格虛擬化、httpOnly cookie、CD 自動部署、監控三層、**找 3–5 個試用者** |
| **3** | 6–12 月 | **產品化與 DB 上雲** | 前端 40% / 雲端 35% / 後端 25% | K 線 + 籌碼趨勢圖(核心賣點)、URL 即狀態、RWD/a11y、staging、Terraform、DB 遷移 Neon、複合索引 + stock_metrics 表、**雲端 IP 爬蟲 spike** |
| **4** | 12–24 月 | **雲遷移與差異化(三選一序列)** | 依序:① Cloud Run 遷移 → ② Alert Engine + LINE → ③ 回測引擎 | zero-downtime canary、Cloud Run Jobs 排程、全 IaC、成本治理;之後才做警報與回測 |

**Phase gate(不通過不進下一階段)**:
- Phase 1 → 2:CI 綠燈且 coverage ≥ 50%;`alembic upgrade head` 可從零建 schema;連續兩個週末排程成功寫入正確日期資料;完成一次 restore 演練。
- Phase 2 → 3:陌生人可以自行註冊(email 驗證)→ 篩選 → 建 watchlist 全程無需你介入;pipeline 失敗會在 30 分鐘內通知到手機;至少 3 位試用者給過回饋。
- Phase 3 → 4:prod 跑在 Neon 上連續 4 週無異常;`terraform plan` 對現有資源 no changes;Lighthouse/E2E/axe 全綠。
- Phase 4 內部:雲遷移驗收(zero-downtime、連續 8 週 pipeline 無人工介入)通過後,才開工 Alert Engine。

## 5. 跨軌架構決議(ADR)

以下決議解決三份單軌文件之間的矛盾,**效力高於單軌文件**。正式 ADR 檔案日後放 `docs/adr/`,此處為索引與結論。

### ADR-1|終態架構:Cloud Run 版,不含常駐 Redis/worker
後端軌原規劃 ARQ worker + Redis(queue/cache/pub-sub)+ WebSocket;雲端軌終態是 Cloud Run min-instances=0 + Cloud Run Jobs——兩者直接衝突(ARQ 需常駐 worker、WebSocket 掛住實例、Memorystore ~$25+/月打爆成本目標)。**決議**:終態以 Cloud Run 為準。
- 排程/背景工作:目標 **Cloud Run Jobs + Cloud Scheduler**,不引入 ARQ(省下 6 週)。
- WebSocket 移至 icebox;「資料已更新」通知改由 LINE push / Web Push 擇一承擔。
- Redis 的三個用途拆開處理:cache → 資料週更,HTTP cache header + TanStack Query 已足夠,必要時 Upstash free tier;rate limit → slowapi in-memory(單實例夠用)或 Upstash;queue → Cloud Run Jobs 取代。VPS 期間若已裝 Redis 可先用,但**不得成為遷移阻礙**。
- 若日後接入盤中即時資料源,重啟此 ADR,屆時終態改 Fly.io/常駐 VM。

### ADR-2|排程系統只演進兩次,不重寫四次
Phase 1:`printenv > /etc/environment` 止血(半天)→ Phase 2:**host systemd timer** 跑 `docker compose run --rm scheduler`(去 cron-in-container)→ Phase 4:**Cloud Run Jobs + Cloud Scheduler**。刪除「容器內 APScheduler」與「ARQ cron」兩個中間態。

### ADR-3|監控統一 Grafana Cloud,不自架
後端軌 Phase 3 的自架 Prometheus + Grafana 刪除(避免與 app + Postgres 擠 4GB VPS 造成 OOM,也避免重複建置)。統一採用:Grafana Cloud free tier + Alloy(雲端軌 Phase 2)+ Sentry + Uptime Kuma(跑在**另一台**免費機)。後端軌只保留 `prometheus-fastapi-instrumentator` 輸出 `/metrics` 與自訂業務指標(`pipeline_last_success_timestamp` 等)。**業務級告警(pipeline 超過 8 天沒新資料)優先於機器級告警。**

### ADR-4|基礎設施項目唯一 owner
工時不重複計算、實作不做兩套:

| 項目 | Owner 軌 | 其他軌角色 |
|---|---|---|
| Alembic 導入 | 後端(Phase 1) | 雲端 deploy.sh 只「呼叫」`alembic upgrade head` |
| pg_dump 備份 + rclone 異地 + restore 演練 | 雲端(Phase 1–2) | 後端 Phase 3 對應項為依賴 |
| GitHub Actions CI 骨架 | 雲端(Phase 2 統籌) | 後端/前端各自貢獻自己的 job(pytest / eslint+vitest) |
| Dockerfile 修復(multi-stage、non-root) | 雲端(Phase 1) | — |
| secrets 管理(SOPS/Doppler → Secret Manager) | 雲端 | — |

### ADR-5|screen API:全量回傳 + 上限保護,前端虛擬化保留
後端軌要加分頁(預設 50)、前端軌要虛擬化 1,900 列——二者互斥。**決議**:本產品的核心體驗是「拖滑桿全表即時篩選」,且資料量小(~2,000 列、週更、可快取),採 **全量回傳 + `limit` 上限保護(如 2000)+ ETag/Cache-Control**;前端虛擬化照做。伺服器分頁不做,`limit/offset` 參數保留為 API 消費者(未來 bot)的可選項。

### ADR-6|Auth token 與 domain 策略(cookie 遷移的前置決策)
- Token 規格統一:**refresh token → httpOnly cookie(後端負責);access token(30 分)→ 前端記憶體,不落地 localStorage**。
- Domain 策略:前後端必須同 eTLD+1(如 `app.example.com` + `api.example.com`,cookie `Domain=.example.com; SameSite=Lax`)。前端搬 Cloudflare Pages 時**必須掛 custom domain**——`*.pages.dev` 與 API 跨站會讓 Lax cookie 失效;Pages 的 PR preview URL 無法登入屬已知限制,E2E 測試走 staging domain。

### ADR-7|OpenAPI codegen 順序
後端先完成(各 1–2h,提前到後端 Phase 1):Decimal 序列化改 float、所有 route 補 `response_model`、決定 `/api/v1` 前綴——**之後**前端才做 openapi-typescript codegen。從漂移中的 schema codegen 等於做兩次。

### ADR-8|爬蟲上雲前先驗證 IP 不被擋
TWSE/TPEX/TDCC 對資料中心 IP 有封鎖前例。雲端 Phase 3 加半天 spike:從 GCP `asia-east1` 實測四個資料源全部可爬。可爬 → Phase 4 pipeline 上 Cloud Run Jobs;被擋 → pipeline 留 VPS(或評估固定 egress IP 成本),**只搬 API**。

### ADR-9|Neon 容量與真實成本 gate
Phase 2 起存完整籌碼歷史 + Phase 4 backfill 3–5 年 OHLCV 幾乎必然超過 Neon Free 0.5GB。遷移前實測 `pg_database_size`,成本情境含 Neon Launch($19/月);或明訂冷資料歸檔策略(> 2 年的原始列轉 parquet 存 R2)。「月費 < $20」的驗收標準改為**含 DB 的真實數字**(合理目標:< $30)。

### ADR-10|第一次成功 restore 演練 = 對外開放流量的 gate
備份還原驗證的順序**先於 DNS 切換**。沒演練過的備份等於沒有備份。

### ADR-11|Phase 1 P0 修復的誠實工時
8 個 P0 項目(含 python-jose → PyJWT 遷移、兩處 race condition、bcrypt async 包裝、cron 修復)實際約 20–25h,排 **3–4 週**。python-jose 遷移移到第一批 auth 測試寫完之後做——先有測試網再換庫。

### ADR-12|通知管道二選一、Phase 4 三選一
- PWA + Web Push(前端軌)與 LINE bot(後端軌)是重複的通知管道,依 Phase 2–3 的試用者回饋**二選一**(台灣用戶預期 LINE 勝出,屆時 PWA 只保留「可安裝 + 離線快取」不做 push)。
- LINE Messaging API 免費層每月推播則數有限且 Official Account 需審核:Alert Engine 開工前先做**費用試算 + 訊息聚合策略**(每人每週一則 digest,而非逐事件推)。
- Phase 4 強制依序:**雲遷移 → Alert/LINE → 回測**,前項驗收通過才開工後項。

### ADR-13|Icebox(有真實用戶需求或求職衝刺時才做)
i18n/en.json(~10h)、TanStack Router 遷移(~12h,用 React Router + URLSearchParams 即可)、Storybook + Chromatic + design system workspace package(~22h)、WebSocket(~1 個月)、Kubernetes(僅保留 kind 本地認知練習)、TimescaleDB/partitioning(觸發條件:> 500 萬列或查詢 p95 > 500ms)。合計釋放 ~44h+ 給產品功能。

## 6. 合規與產品補強(單軌文件未涵蓋,一律納入)

1. **資料來源合法性盤點(Phase 1,對外開放前完成)**:逐一確認 TWSE/TPEX/TDCC/MOPS/HiStock 的 ToS 與再散布條款——HiStock 是商業網站,爬取並再散布其資料有著作權風險,需評估替代來源或取得授權;交易所資訊再利用有授權費議題。網站加**免責聲明**(非投資建議)與**隱私權政策**(蒐集 email 屬個資,《個資法》要求告知與刪除機制)。提供選股/警示服務給公眾,需留意台灣《證券投資信託及顧問法》對投顧行為的界線——免費、不推薦個股買賣點、僅呈現公開資料統計,是相對安全的定位。
2. **產品驗證提前到 Phase 1–2**:上線後立即找 3–5 個試用者(朋友、PTT Stock 板),加最簡單的匿名使用量統計(哪個功能有人用);用回饋決定 Phase 3–4 的功能取捨。每個大型功能(回測、bot、PWA)都設「不做的條件」(kill criteria)。
3. **對外開放的帳號基本功(Phase 2,優先於 refresh rotation 打磨)**:email 驗證、忘記密碼/重設、刪除帳號。沒有這三樣,真實用戶進不來、垃圾註冊擋不掉、個資法義務無法履行。
4. **staging 資料匿名化**:staging DB 從 prod 備份還原時,users 表 email 打碼、密碼 hash 隨機化。
5. **效能驗收採遷移前後雙基準**:screen p95 目標在「本機 Postgres」與「Neon(~50ms RTT)+ Cloud Run」是兩組不同數字;「合併 4 個 max-date 查詢、減少每請求 round-trip」是 Neon 遷移的**前置必要條件**而非選項。
6. **每 Phase 結尾 30 分鐘 sustainability review**:使用者數 / 自己使用頻率 / 剩餘動力三項打分;低於門檻就啟動「維運最小化模式」(只留備份 + 監控 + 安全更新)。這本身就是成熟的工程判斷。

## 7. 兩年後的驗收(終極目標)

- 系統:zero-downtime deploy、連續 8 週 pipeline 無人工介入、月成本 < $30(含 DB)、所有告警都被真實觸發並處理過。
- 產品:有一群每週主動打開的真實使用者,K 線 + 籌碼趨勢 + 個人化警報是使用主因。
- 個人:能對著架構圖完整講 45 分鐘——每個元件為什麼選它、錢花在哪、掛掉會怎樣、怎麼知道掛掉;履歷上的每個子句都對應一個驗收標準,可被追問三層而不虛。

## 8. 學習地圖

完整版(順序、資源、投入、FAANG 面試價值對照)見 [`03-cloud-devops.md`](./03-cloud-devops.md) 末節。一句話版:**Docker 深化 → Linux/網路營運 → GitHub Actions → SRE/可觀測性 → PostgreSQL 營運 → Terraform → Cloud Run →(可選)AWS SAA 證照 → System Design 總整理**,每項技能都掛在本藍圖的一個真實 milestone 上學,不獨立刷課。
