# 07 · 股價淨值比（PB）估值與同產業比較

> 制定日期：2026-11-07 · 修訂：2026-11-07（依參考文章全文調整）· 狀態：**規劃中，待確認後實作**
> 參考文章：BOS 巴菲特線上學院〈股價淨值比是什麼？多少算便宜要看產業〉（2026-09-22）
> <https://buffettonlineschool.com.tw/price-to-book/>

## 1. 目標

1. 在篩選結果中，替每檔股票顯示 **最新股價淨值比（PB）** 與 **每股淨值**，並標示分母採用的財報季別。
2. 給予 **便宜／普通／昂貴** 三個評級。
3. 利用既有的 `stocks.industry`，可展開 **同產業比較**，把同產業股票的 PB 排在一起看。

## 2. 參考文章的結論，以及對設計的影響

| 文章重點 | 設計上的對應 |
|---|---|
| PB = 股價 ÷ 每股淨值；每股淨值 = 股東權益 ÷ 流通股數 | 公式不變 |
| 「低於 1 就便宜」無法套用所有股票：半導體產業中位數 3.17、塑膠 0.78，相差 4.1 倍；低於 1 的比例塑膠 76%、半導體 3% | **不採用單一絕對門檻**，評級以同產業相對位置為主 |
| 產業內部差距更大（半導體 96 家，最低 0.55、最高 58.97） | 用百分位排名，不用平均值；平均值會被極端值拉走 |
| 家數不到 10 家的產業不單獨列 | 同產業樣本 **少於 10 檔不給產業評級** |
| 產業高低順序穩定，但數值會變（一年內產業中位數變動 16%，半導體差 41%） | **不寫死任何產業門檻**，每天依當日資料重算 |
| 證交所每日公布全體上市公司 PB，同一天所有公司的分母季別一致；上櫃在櫃買中心有對應的表 | **資料來源改用交易所每日表**，不自行抓資產負債表，比較基準才一致 |
| 淨值為負時比值沒有意義，證交所的表會留空 | PB 空白 → 不評級，畫面顯示「淨值為負或無資料」 |
| 要跟同產業、也要跟公司自己的歷史一起看 | 第一階段做同產業；第二階段加上自身歷史 |
| 低 PB 最常見的原因是生意本來就不太賺錢；價值陷阱的分水嶺是由盈轉虧 | 同一張表附有本益比，**本益比空白（虧損）時加註「虧損中」提醒** |
| 金融保險的 PB 分布最集中（0.73–2.55），這把尺用在金融股最可靠 | 產業比較面板顯示產業的 PB 分布範圍，讓使用者看得出集中或分散 |

## 3. 評級規則

### 3.1 第一階段：同產業相對評級

| 評級 | 條件 |
|---|---|
| 便宜 | 產業 PB 百分位 ≤ 25% |
| 昂貴 | 產業 PB 百分位 ≥ 75% |
| 普通 | 其餘 |
| 不評級 | PB 空白（淨值為負或無資料）、或同產業有效樣本少於 10 檔 |

補充規則：

- 百分位以 **全市場同產業**（上市 + 上櫃合併）計算，不限於篩選結果，評級才不會因篩選條件改變而跳動。
- 樣本不足 10 檔的產業不給評級，畫面只顯示 PB 與「產業樣本不足」，不改用絕對門檻。
- 附加標籤（不影響評級）：
  - **PB < 1**：「股價低於淨值」
  - **本益比空白**：「虧損中」，提醒留意價值陷阱
- 門檻（25% / 75% / 最少樣本 10 檔）集中定義為常數，日後調整只需改一處。

### 3.2 第二階段：加入自身歷史

- 以個股近 5 年的 PB（每月取樣一天）計算目前 PB 在自己歷史中的百分位，同樣以 25% / 75% 分成三級。
- 畫面上兩個評級並列：「產業：便宜」「自身歷史：普通」。兩者一致時可信度較高，不一致時提醒使用者再查獲利與現金流。
- 歷史資料不足 3 年（36 個取樣點）的個股，只顯示產業評級。
- 另外顯示參考價位：每股淨值 × 自身歷史 PB 的第 25／50／75 百分位。這組價位是本專案自訂，文章並未提出。

## 4. 資料來源

| 市場 | 端點 | 內容 |
|---|---|---|
| 上市 | `www.twse.com.tw/rwd/zh/afterTrading/BWIBBU_d?date=YYYYMMDD&selectType=ALL&response=json` | 全體上市股票當日收盤價、殖利率、本益比、股價淨值比、財報年／季 |
| 上櫃 | 櫃買中心「個股本益比、殖利率及股價淨值比」依日期查詢的表 | 同上 |

- 一個交易日、一個市場只需 **一次請求**，納入現有的每日盤後 pipeline，與行情使用同一個交易日。
- 延續 `twse_scraper.py` 的原則：使用 `www.twse.com.tw` 當天就更新的端點，不使用落後一天的 openapi。
- **每股淨值以「收盤價 ÷ PB」推算**，與交易所的 PB 使用同一個分母，不會出現 PB 與淨值對不起來的情況。
  交易所的 PB 只到小數兩位，推算出的淨值誤差約在 0.5% 以內，畫面上標示「依交易所股價淨值比推算」。
- 兩個端點的實際欄位名稱，實作第一步以真實回應存成 `tests/fixtures/` 後再確認
  （規劃時的開發環境無法連到交易所）。

## 5. 資料庫設計

新增一張表（Alembic migration）：

```text
valuations
  id             BIGSERIAL PK
  stock_code     VARCHAR(10)   NOT NULL
  trade_date     DATE          NOT NULL
  pb_ratio       NUMERIC(8,2)  NULL      -- 淨值為負時交易所留空 → NULL
  pe_ratio       NUMERIC(8,2)  NULL      -- 虧損時留空 → NULL
  dividend_yield NUMERIC(6,2)  NULL      -- %
  bvps           NUMERIC(10,2) NULL      -- 收盤價 ÷ PB，入庫時算好
  fin_period     VARCHAR(8)    NULL      -- 財報年／季，例如 "115Q2"
  UNIQUE (stock_code, trade_date)        -- upsert 冪等，與其他時序表一致
  INDEX  (trade_date)
```

- 本益比與殖利率同一張表就有，一併存下，第二階段與日後的本益比評價不必再抓一次。
- 每日約 1,900 筆，一年約 47 萬筆，量級與 `daily_quotes` 相同。
- 評級 **不落地**，查詢時即時計算：產業分布每天都在變，存下來反而要處理過期問題。

## 6. 後端

### 6.1 爬蟲與 Pipeline

- `twse_scraper.py`、`tpex_scraper.py` 各新增 `fetch_valuation_on(client, trade_date)`，回傳
  `code, trade_date, pb_ratio, pe_ratio, dividend_yield, bvps, fin_period`。
- `data_pipeline.run_quotes_pipeline()`：拿到兩市各自的交易日後，與三大法人一起並行抓取，寫入 `valuations`。
- `run_offline_pipeline()` 與測試 fixture 同步補上。
- 第二階段新增 `scripts/backfill_valuation.py`：近 5 年每月最後一個交易日各抓一次，
  每個市場約 60 次請求（逐日回補約 1,200 次，少 95%），沿用既有回補腳本的請求間隔。

### 6.2 估值計算（單一 SQL）

```sql
WITH v AS (                -- 每檔最新一筆估值
  SELECT DISTINCT ON (stock_code) stock_code, trade_date, pb_ratio, pe_ratio, bvps, fin_period
  FROM valuations ORDER BY stock_code, trade_date DESC
), base AS (
  SELECT s.code, s.industry, v.*
  FROM stocks s JOIN v ON v.stock_code = s.code
  WHERE v.pb_ratio IS NOT NULL
), ind AS (                -- 產業中位數、範圍、樣本數
  SELECT industry,
         PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY pb_ratio) AS ind_median,
         MIN(pb_ratio) AS ind_min, MAX(pb_ratio) AS ind_max,
         COUNT(*)      AS ind_n
  FROM base GROUP BY industry
)
SELECT base.*, ind.ind_median, ind.ind_min, ind.ind_max, ind.ind_n,
       PERCENT_RANK() OVER (PARTITION BY base.industry ORDER BY base.pb_ratio) AS ind_pct
FROM base JOIN ind USING (industry);
```

- 時間複雜度 O(N log N)（N ≈ 1,900，排序由資料庫完成），空間 O(N)，沒有 N+1 查詢。
- `/api/screen` 把這段當子查詢 LEFT JOIN 進現有主查詢，沒有估值資料的股票照常出現，只是評級欄位為空。
- 評級判定寫成純函式 `rate_pb(pb, ind_pct, ind_n) -> "cheap" | "fair" | "expensive" | None`，方便單元測試。

### 6.3 API

| 端點 | 變更 |
|---|---|
| `GET /api/screen` | `ScreenItem` 新增 `pb_ratio`、`pe_ratio`、`bvps`、`fin_period`、`pb_rating`、`industry_pb_pct`、`industry_pb_median`、`industry_n`；新增查詢參數 `pb_ratings`（可複選，篩出指定評級） |
| `GET /api/valuation/industry` | **新增**。參數 `industry`（必填）、`codes`（選填，帶入時只回傳這些股票）。回傳該產業每檔的收盤、淨值、PB、本益比、百分位、評級，以及產業中位數、最小值、最大值、樣本數，依 PB 由低到高排序 |
| `GET /api/stocks/{code}` | `StockDetail` 一併帶出 PB、淨值與評級 |

## 7. 前端

1. **篩選結果表格**（`DashboardPage.tsx`）新增欄位：
   - PB（可排序）
   - 每股淨值（滑鼠移上顯示財報季別與「依交易所股價淨值比推算」）
   - 評級標籤：便宜（綠）／普通（灰）／昂貴（橘），旁邊附「低於淨值」「虧損中」小標籤。
     刻意不用紅色：台股慣例紅色代表上漲，用紅色表示昂貴容易誤讀。
2. **篩選列**新增評級複選（便宜／普通／昂貴），樣式比照現有市場切換。
3. **同產業比較**：點擊表格中的產業標籤開啟側邊面板：
   - 預設「全市場同產業」，可切換「只看篩選結果內」；
   - 依 PB 由低到高的橫條圖，標出產業中位數參考線，目前點選的股票以高亮顯示；
   - 面板上方顯示產業中位數、範圍（最小～最大）、樣本數，範圍窄代表這把尺在該產業較可靠；
   - 下方表格列出代號、名稱、收盤、淨值、PB、本益比、百分位、評級。
4. 面板底部固定一行說明：「PB 低不等於該買，常見原因是獲利能力較弱，請一併查看獲利與現金流。」
5. CSV 匯出加入 PB、淨值、本益比、評級。

## 8. 測試

- 解析器：以兩市真實回應存成 fixture，驗證 PB、本益比空白時解析為 `None`，財報季別正確轉換。
- `rate_pb`：邊界值（剛好 25% / 75%、樣本 9 檔與 10 檔、PB 為空）。
- API：沿用 `test_api_offline.py` 的方式，驗證 `/api/screen` 新欄位與 `/api/valuation/industry`。
- Migration：`verify_migration_schema.py` 確認新表與模型一致。

## 9. 工作拆分與估時

| # | 項目 | 估時 |
|---|---|---|
| 1 | 實測兩市端點、存 fixture、寫解析器 | 2h |
| 2 | `valuations` 模型 + migration + upsert + 接入每日 pipeline | 1.5h |
| 3 | 估值 SQL、`rate_pb`、`/api/screen` 擴充、`/api/valuation/industry` | 2.5h |
| 4 | 前端表格欄位、評級篩選、CSV | 2h |
| 5 | 同產業比較面板（含橫條圖） | 2.5h |
| 6 | 測試與文件 | 1.5h |
| | **第一階段合計** | **約 12h** |
| 7 | 第二階段：5 年月取樣回補、自身歷史評級、參考價位、個股 PB 走勢圖 | 約 6h |

## 10. 決議與待確認

已依文章決定：

- 評級以 **同產業相對位置** 為主，不使用「低於 1 就便宜」的單一門檻。
- 資料來源採 **交易所每日公布的股價淨值比表**，分母季別一致。
- 產業樣本少於 10 檔不給產業評級。

預設做法（如有不同意見請告知）：

- 同產業比較預設「全市場同產業」，可切換為「只看篩選結果內」。
- 第一階段完成後接著做第二階段（自身歷史）。
