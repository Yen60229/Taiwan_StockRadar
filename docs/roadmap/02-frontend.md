# 前端路線圖 (Frontend Roadmap)

> ⚠️ **閱讀前必看**:本文件是「前端單軌視角」,工時假設(每週 6-10h)為單軌獨立估計;實際上三軌共用同一個時間池,執行時以 [`README.md`](./README.md) 的**整合時間表**與**跨軌決議(ADR)**為準。本文件中受 ADR 修訂的項目:
> - Phase 1 的 OpenAPI codegen 必須等後端先修 Decimal 序列化 + response_model + /api/v1 決策(**ADR-7**)
> - Phase 2 的 httpOnly cookie 遷移必須先確定 domain 策略與 token 存放規格(**ADR-6**)
> - Phase 2 的表格虛擬化**保留**——產品決策採「全量回傳 + 前端虛擬化」(**ADR-5**)
> - Phase 3 的 TanStack Router 遷移、i18n(en.json)與 Phase 3-4 的 Storybook/Chromatic/workspace package:移至 **icebox**(ADR-13),用 React Router + URLSearchParams 達成「URL 即狀態」即可
> - Phase 4 的 PWA + Web Push 與後端軌的 LINE bot 是重複通知管道,依用戶回饋**二選一**(ADR-12)


> 現況基準:~1,000 LOC 的 Vite + React 18 SPA,3 個頁面、無測試、無 lockfile、無 lint、`DashboardPage.tsx` 580 行巨石、1,900 列表格無虛擬化、JWT 存兩份 localStorage、API 型別與後端 Decimal 序列化不一致。以下假設 solo developer 每週投入 6-10 小時。

---

## Phase 1(0-3 月):止血 — 修復技術債、建立工程基線

### 目標
把「能跑」變成「可以放心改」:可重現的 build、統一的 auth 狀態、型別正確的 API 邊界、第一批單元測試、拆掉巨石元件。**這一階段不做新功能。**

### 具體任務

**Week 1-2:工程基線(約 8h)**
- [ ] 提交 `package-lock.json`,`frontend/Dockerfile` 改為 `COPY package*.json` + `npm ci`;加 `.dockerignore`(排除 `node_modules`、`dist`)
- [ ] 安裝 ESLint(flat config + `typescript-eslint` + `eslint-plugin-react-hooks` + `eslint-plugin-jsx-a11y`)與 Prettier;加 `lint`、`format`、`typecheck` scripts
- [ ] 新增 `tsconfig.node.json` project reference,讓 `vite.config.ts` 納入型別檢查
- [ ] GitHub Actions:`frontend-ci.yml` 跑 `npm ci && npm run lint && npm run typecheck && npm run build`

**Week 3-4:Auth 狀態統一(約 6h)**
- [ ] 刪除 `store/auth.ts:18` 手寫的第二份 `localStorage("token")`,axios interceptor 改讀 `useAuth.getState().token`(`api/client.ts:11`)
- [ ] 401 handler 改呼叫 `useAuth.getState().logout()`(同時清空 zustand persist blob),用 router navigate 取代 `location.href='/login'` 硬跳轉,消除分析中提到的 401 bounce loop
- [ ] `PrivateRoute` 加 `replace` 並用 `state={{ from: location }}` 保留目的地,登入後導回

**Week 5-7:API 邊界修正(約 10h)**
- [ ] 引入 **OpenAPI codegen**(推薦 `openapi-typescript` + `openapi-fetch`,或 `orval`),從 FastAPI 的 `/openapi.json` 產生型別,取代 `client.ts` 手寫且已漂移的 interface(Decimal 序列化成 string 但宣告為 `number` 的問題)
- [ ] 短期解:在 `client.ts` 加 response transform 統一把 Decimal string 轉 number,刪掉 `DashboardPage.tsx` 散落 ~15 處的 `Number()` 防禦性轉型(長期由後端改 `model_config` 序列化 float 解決)
- [ ] 補齊 `authApi`/`watchlistApi` 的回傳型別;`LoginPage.tsx:24-26` 的錯誤處理支援 FastAPI 422 的 `detail` array 格式(避免 `[object Object]`)
- [ ] 修 `exportCSV`:欄位加引號 escape、呼叫 `URL.revokeObjectURL`

**Week 8-10:拆巨石 + 首批測試(約 14h)**
- [ ] 建立目錄結構:`components/`(`ScreenTable`、`FilterBar`、`ConcCell`、`MarketBadge`…)、`hooks/`(`useScreenQuery`、`useSort`、`useDebounce`)、`lib/`(`industryMap.ts`、`csv.ts`、`format.ts`),把 `DashboardPage.tsx` 壓到 <150 行
- [ ] Slider 濾鏡加 300ms debounce(自寫 `useDebouncedValue` hook),消除拖曳一次發 19 個 `/screen` request 的問題
- [ ] 安裝 **Vitest + React Testing Library + MSW**;第一批測試:`csv.ts`(逗號 escape)、`useSort`(排序方向)、`FilterBar`(debounce 行為)、axios 401 interceptor(用 MSW mock)
- [ ] `DashboardPage` 消費 `isError`,失敗時顯示錯誤 + 重試按鈕,不再誤顯示「沒有符合條件的標的」;`StockPage` 區分 404 與網路錯誤

**Week 11-12:基本效能(約 6h)**
- [ ] Route-level code splitting:`StockPage` 改 `React.lazy` + `Suspense`,讓 Recharts 不進首頁 bundle;`vite.config.ts` 開 `manualChunks` 分離 vendor
- [ ] `nginx.conf` / Caddyfile 加 CSP header;Google Fonts 改 self-host(`@fontsource/inter`、`@fontsource/noto-sans-tc`),消除第三方 CDN 依賴與 CSP 破口

### 學習重點/資源
- **TanStack Query 官方 docs**(重讀 query invalidation、`isError`/`error` 消費模式)
- **Testing Library 哲學**:Kent C. Dodds〈Testing Implementation Details〉、MSW docs(mock 在 network 層而非 axios 層)
- **openapi-typescript** 官方指南 — 理解「schema 為單一真實來源」的 contract-first 思維
- ESLint flat config 遷移指南(2024+ 的新格式)

### 驗收標準
- `npm ci && npm run lint && npm run typecheck && npm run test && npm run build` 在 CI 全綠,PR 必須通過才能 merge
- localStorage 只剩一份 token 來源;401 後重新整理不會出現 bounce loop(手動驗證腳本寫進 PR description)
- `client.ts` 無任何 `any`;`DashboardPage.tsx` <150 行;grep `Number(` 在頁面層為 0
- Vitest coverage:`lib/` 與 `hooks/` ≥ 80%;首屏 JS bundle 不含 Recharts(用 `npx vite-bundle-visualizer` 驗證)

---

## Phase 2(3-6 月):表格重構、Auth 安全、E2E 測試

### 目標
用 TanStack Table + 虛擬化解決 1,900 列效能問題,token 遷移到 httpOnly cookie,建立 Playwright E2E 護欄,統一 design token。

### 具體任務

**表格重構(約 16h)**
- [ ] 以 **TanStack Table v8** 重寫 `ResizableTable`:column defs、`getSortedRowModel`、內建 column sizing 取代手寫 mousemove resize(現在每 pixel setState 一次)
- [ ] 加 **@tanstack/react-virtual** 虛擬化 1,900 列;hover 效果改純 CSS `:hover`,刪掉 `useState` hover tracking(消除全表 re-render)
- [ ] Row 元件 `React.memo`,style objects 提出到 module scope
- [ ] 表格狀態(排序、欄寬、顯示欄位)持久化到 localStorage(獨立的 zustand `useTableStore`)

**Auth 安全:httpOnly cookie 遷移(約 10h,需後端配合)**
- [ ] 後端 `/api/auth/login` 改 `Set-Cookie: access_token=…; HttpOnly; Secure; SameSite=Lax`,加 `/api/auth/logout`(清 cookie)與 `/api/auth/refresh`
- [ ] 前端:axios 改 `withCredentials: true`,刪除 Bearer interceptor 與 localStorage token;zustand 只存 `user` profile(非敏感),登入狀態以 `/api/auth/me` 為準
- [ ] 加 CSRF 防護(SameSite=Lax + 自訂 header double-submit,或後端驗 `Origin`)
- [ ] 401 時先嘗試 refresh 再登出(axios response interceptor 的 retry-once 模式)

**Design token 統一(約 8h)**
- [ ] 決策:引入 **Tailwind CSS v4**(CSS-first config,把 `index.css` 現有 tokens 對映成 theme variables)— 或保守路線用 CSS Modules + 現有 variables。建議 Tailwind:社群資源多、和 inline-style 心智模型接近
- [ ] 逐頁把 hardcoded hex/rgba(`#00d8ff`、`rgba(0,150,255,.12)` 重複數十次)換成 token;刪除死 token(`--radius-md`、`--bg-deep`)
- [ ] 抽出基礎元件:`Button`、`Input`、`Badge`、`Card`、`Skeleton` 放進 `components/ui/`

**UX:樂觀更新與載入狀態(約 6h)**
- [ ] Watchlist 加/移除改 `onMutate` 樂觀更新(直接 `setQueryData` 改該列的 `in_watchlist`),取代整包 1,900 列 refetch
- [ ] `/screen` 載入中顯示 skeleton rows(配合 `placeholderData: keepPreviousData` 讓濾鏡切換不閃白)

**Playwright E2E(約 10h)**
- [ ] 安裝 Playwright,CI 用 `docker compose up` 起 API + seed 測試資料(或用 MSW 的 route mock 走純前端模式,兩者擇一先行)
- [ ] 核心三條 flow:註冊→登入→登出;調整濾鏡→驗證表格結果與 URL;加入 watchlist→重新整理仍在
- [ ] CI 上傳 trace/screenshot artifacts 供失敗除錯

### 學習重點/資源
- **TanStack Table + Virtual 官方範例**(virtualized rows example 可直接參考)
- **OWASP Cheat Sheets**:JWT Storage、CSRF Prevention — 理解為什麼 httpOnly cookie + SameSite 優於 localStorage
- **Playwright docs**:fixtures、`webServer` config、trace viewer
- Tailwind v4 theme variables 文件;閱讀一個成熟 design system(如 Radix Themes)的 token 命名法

### 驗收標準
- 1,900 列表格:滾動維持 60fps(Chrome DevTools Performance 錄製佐證),DOM 中同時存在的 `<tr>` < 50
- `document.cookie` 與 `localStorage` 皆讀不到 token;XSS 注入 `alert(localStorage.getItem('token'))` 拿到 `null`
- Watchlist 點擊後 UI 立即更新,network tab 無全表 refetch
- Playwright 3 條 flow 在 CI 穩定通過(連續 10 次無 flake);頁面層 hardcoded 色碼 grep count 較 Phase 1 減少 90%

---

## Phase 3(6-12 月):產品級圖表、路由升級、i18n、RWD、可及性

### 目標
從「篩選器工具」升級成「看盤體驗」:K 線與籌碼趨勢圖、URL 即狀態、手機可用、雙主題、WCAG AA、Storybook 元件文件化。

### 具體任務

**圖表升級(約 20h)**
- [ ] 引入 **lightweight-charts**(TradingView 開源,45KB,金融圖表首選;ECharts 備案適合複雜混合圖),`StockPage` 加日 K candlestick + 成交量副圖(資料來自 `daily_quotes`,需後端補 `/api/stocks/{code}/ohlcv` 端點)
- [ ] **籌碼趨勢圖**:400 張以上大戶持股比率週線疊加股價(雙 Y 軸)——這是本產品的核心賣點,值得花時間打磨(前提:Phase 2 後端已移除 40% scrape-time filter 保留完整歷史)
- [ ] 三大法人 30 日買賣超改堆疊 bar(外資/投信/自營分色),與現有 Recharts LineChart 汰換後移除 Recharts 依賴
- [ ] 圖表元件全部 `React.lazy`,各自獨立 chunk

**路由與狀態架構(約 12h)**
- [ ] 遷移到 **TanStack Router**(型別安全的 search params 是關鍵賣點)或最小改動用 React Router 6.4+ data APIs;篩選條件(min_avg_vol、min_conc、market、search、sort)全部進 URL search params —— 可分享篩選結果連結、重新整理不丟狀態
- [ ] 狀態架構收斂文件化:server state → TanStack Query、URL state → router search params、UI 偏好(欄寬/主題)→ zustand persist、auth → cookie + `/me` query;寫進 `frontend/ARCHITECTURE.md`
- [ ] 修復 `client.ts:94-95` array param 序列化(axios `paramsSerializer` 用 repeat 格式對齊 FastAPI `Query(None)`)

**i18n + 主題(約 10h)**
- [ ] **react-i18next** 抽出所有 zh-TW 字串到 `locales/zh-TW.json`,補 `en.json`(擴大用戶面、也是履歷亮點);數字/日期用 `Intl.NumberFormat`/`Intl.DateTimeFormat`
- [ ] Light/dark theme:token 全走 CSS variables 後,加 `data-theme` 切換 + `prefers-color-scheme` 預設 + zustand 持久化

**RWD/Mobile(約 12h)**
- [ ] 手機版 Dashboard:表格改卡片式清單(<768px breakpoint),保留關鍵 4 欄;FilterBar 收進 bottom sheet
- [ ] 觸控:排序改 tap、移除 hover-only 資訊、圖表支援 pinch zoom(lightweight-charts 內建)

**可及性(約 8h)**
- [ ] 修復分析列出的問題:sortable `<th>` 加 `role="button"` + `aria-sort` + keyboard handler;row 點擊改真 `<a>`(可 cmd+click 開新分頁);focus ring 取代 `outline:none`;`#3d5a7a` 等低對比色調到 AA(4.5:1);loading 加 `aria-live`
- [ ] 鍵盤導航:`/` 聚焦搜尋、`j/k` 上下列、`Enter` 進個股、`w` toggle watchlist
- [ ] CI 加 `axe-core`(Playwright 整合)自動掃描

**Storybook + 效能預算(約 10h)**
- [ ] Storybook 8 建置 `components/ui/` 與 `ScreenTable`、圖表元件的 stories;加 Chromatic 或 `@storybook/test-runner` 做 visual regression
- [ ] **Lighthouse CI** 進 GitHub Actions:預算 Performance ≥ 90、首屏 JS < 250KB gzipped、LCP < 2.5s;超標即 CI fail

### 學習重點/資源
- lightweight-charts 官方 tutorials(series types、雙 pane、time scale sync)
- TanStack Router docs 的 search params validation(用 zod schema)—— 這是「URL 即狀態」的最佳教材
- **WAI-ARIA Authoring Practices Guide (APG)** 的 grid/table pattern;WebAIM contrast checker
- Storybook 的 CSF3 + interaction tests;《Inclusive Components》(Heydon Pickering)

### 驗收標準
- 個股頁有可縮放 K 線 + 籌碼趨勢圖,首次載入該 chunk < 100KB gzipped
- 任何篩選組合的 URL 貼給別人打開後看到相同結果
- iPhone SE viewport(375px)無橫向捲動,核心操作(篩選、看個股、watchlist)全部可完成
- axe-core CI 零 critical violations;鍵盤完成「搜尋→選股→加 watchlist」全流程不碰滑鼠
- Lighthouse CI 預算在 CI 強制執行且連續 4 週保持綠燈;Storybook 覆蓋所有 `components/ui/` 元件

---

## Phase 4(12-24 月):PWA、推播、產品化打磨

### 目標
變成使用者「每週會主動打開」的產品:可安裝 PWA、盤後/週報推播、離線可看快取資料、design system 成熟到可以快速長新功能。

### 具體任務

**PWA(約 14h)**
- [ ] **vite-plugin-pwa**(Workbox):manifest、icons、service worker;`/api/screen` 用 stale-while-revalidate 策略快取,離線時顯示上次資料 + 「資料截至 X」banner
- [ ] TanStack Query 加 `persistQueryClient`(IndexedDB via `idb-keyval`)讓冷啟動秒出上次結果
- [ ] 安裝提示(`beforeinstallprompt`)與 iOS Add-to-Home-Screen 引導

**Web Push 推播(約 16h,需後端配合)**
- [ ] 後端:VAPID keys、`push_subscriptions` 表、週報 pipeline 完成後發送 Web Push(`pywebpush`),與現有 Resend email 通知並行
- [ ] 前端:通知權限 UX(在 watchlist 加第 3 檔股票時才問,不要一進站就問)、訂閱管理設定頁
- [ ] 推播情境:每週籌碼更新完成、watchlist 個股新進/跌出篩選名單、大戶持股比率週變化超過閾值(可自訂)

**Design System 成熟化(約 12h)**
- [ ] `components/ui/` 抽成 workspace package(npm workspaces),tokens 輸出 JSON 供未來 mobile app / email template 共用
- [ ] Storybook 部署到 GitHub Pages,含 usage docs 與 do/don't
- [ ] Visual regression(Chromatic free tier 或 Playwright screenshot diff)進 CI

**長期健康度(持續)**
- [ ] 升級 major 版本:React 19(compiler 自動 memo,可刪手寫 `React.memo`)、Router/Query 最新版 —— Phase 1 建立的測試網此時回本
- [ ] 前端錯誤監控:Sentry(`@sentry/react` + source maps 上傳,`vite.config.ts` 開 sourcemap)+ Web Vitals 真實用戶數據(RUM)回報
- [ ] 每季一次「技術債衝刺」:依 Sentry 錯誤率與 bundle size 趨勢決定內容

### 學習重點/資源
- **web.dev 的 PWA 課程** + Workbox strategies(理解 SW 生命週期與 cache 失效,這是 PWA 最容易翻車處)
- Web Push protocol / VAPID 規格(MDN Push API);注意 iOS 16.4+ 才支援且需 Home Screen 安裝
- React 19 升級指南與 React Compiler docs
- 《Design Systems》(Alla Kholmatova)— 何時抽象、何時複製貼上

### 驗收標準
- Lighthouse PWA 全項通過;斷網開啟 app 可看到上次篩選結果與明確的資料時間戳
- 週日 pipeline 跑完 10 分鐘內收到推播,點擊直達當週新進名單(deep link)
- Sentry 週錯誤率 < 0.1% sessions;Web Vitals p75:LCP < 2.5s、INP < 200ms(真實用戶數據)
- 新增一個「含表格+圖表的新頁面」只需組裝既有元件,一個週末(<10h)可上線 —— 這是 design system 成熟的終極驗收

---

## 目標前端架構(Phase 3-4 完成後)

```mermaid
flowchart TB
    subgraph Browser
        SW["Service Worker (Workbox)<br/>SWR cache / offline / push"]
        subgraph App["React App"]
            Router["TanStack Router<br/>(型別安全 search params = 篩選狀態)"]
            subgraph Pages["pages/ (React.lazy per route)"]
                Dash["DashboardPage"]
                Stock["StockPage"]
                Settings["SettingsPage"]
            end
            subgraph Features["features/"]
                Table["ScreenTable<br/>(TanStack Table + Virtual)"]
                Charts["Charts<br/>(lightweight-charts: K線/籌碼趨勢)"]
                WL["Watchlist<br/>(optimistic mutations)"]
            end
            subgraph State["狀態分層"]
                TQ["TanStack Query<br/>server state + persistQueryClient"]
                URL["URL search params<br/>篩選/排序"]
                ZU["Zustand persist<br/>UI 偏好: 主題/欄寬"]
            end
            subgraph Foundation["基礎層"]
                UI["components/ui/<br/>(design tokens + Storybook)"]
                API["api/ generated client<br/>(openapi-typescript, 零手寫型別)"]
                I18N["react-i18next<br/>zh-TW / en"]
            end
        end
    end
    Backend["FastAPI /api/*<br/>httpOnly cookie auth + /openapi.json"]
    Push["Web Push (VAPID)<br/>週報/watchlist 警示"]

    Router --> Pages
    Pages --> Features
    Features --> TQ
    Router --> URL
    Features --> UI
    TQ --> API
    API --> SW
    SW --> Backend
    Backend -. openapi.json codegen .-> API
    Push --> SW

    subgraph Quality["品質防線 (CI)"]
        direction LR
        V["Vitest + RTL + MSW"] --- P["Playwright E2E + axe"] --- L["Lighthouse CI 預算"] --- C["Chromatic 視覺回歸"]
    end
```

**時程總覽**:Phase 1 約 44h、Phase 2 約 50h、Phase 3 約 72h、Phase 4 約 42h+持續維護 —— 以每週 6-10h 計,各階段預留 20-30% buffer 皆可在期限內完成。原則:**每個 Phase 的測試與 CI 投資,都是下個 Phase 敢大改的前提**(Phase 2 敢重寫表格是因為 Phase 1 有測試;Phase 4 敢升 React 19 是因為 Phase 2-3 有 E2E)。