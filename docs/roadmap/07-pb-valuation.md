# 07 · 股價淨值比（PB）估值與同產業比較

> 制定日期：2026-11-07 · 狀態：**規劃中，待確認後實作**
> 參考文章：<https://buffettonlineschool.com.tw/price-to-book/>
> （規劃當下的開發環境無法連到該網站，以下估值規則採用股價淨值比的通用做法；
> 實作前請再對照文章，確認門檻與公式一致。）

## 1. 目標

1. 在篩選結果中，替每檔股票顯示 **最新每股淨值**（BVPS）與其 **財報季別**。
2. 以最新收盤價計算 **股價淨值比**：`PB = 收盤價 ÷ 每股淨值`。
3. 給予 **便宜／普通／昂貴** 三個評級。
4. 利用既有的 `stocks.industry`，可展開 **同產業比較**，把同產業股票的 PB 排在一起看。

非目標（本期不做）：個股 PB 河流圖、本益比與殖利率評價，這兩項放在第二階段。

## 2. 名詞與公式

| 名稱 | 公式 | 說明 |
|---|---|---|
| 每股淨值（BVPS） | （總資產 − 總負債 − 非控制權益）÷ 流通股數 | 直接採用財報公告的「每股參考淨值」，不自行推算 |
| 股價淨值比（PB） | 收盤價 ÷ 每股淨值 | 每日用最新收盤價重算；淨值為季報，一季才更新一次 |
| 產業 PB 百分位 | 該股 PB 在同產業中的排名百分位（0 = 最低、1 = 最高） | 以全市場同產業計算，不限於篩選結果，評級才不會隨篩選條件跳動 |

## 3. 評級規則

### 3.1 第一階段：同產業相對評級（建議預設）

理由：資料只需「最新收盤價 + 最新季報淨值」，現有資料庫已有收盤價與產業別，上線最快；
而不同產業的 PB 水準差異很大（金融股常在 1 倍上下、半導體常在 3 倍以上），
用單一絕對門檻會讓科技股永遠「昂貴」、傳產股永遠「便宜」，參考價值有限。

| 評級 | 條件 |
|---|---|
| 便宜 | 產業 PB 百分位 ≤ 25% |
| 昂貴 | 產業 PB 百分位 ≥ 75% |
| 普通 | 其餘 |
| 不評級 | 每股淨值 ≤ 0（淨值為負）、缺財報、或缺收盤價 |

補充規則：

- **同產業樣本少於 5 檔**時百分位沒有意義，改用絕對門檻：PB < 1 便宜、1 ≤ PB ≤ 2 普通、PB > 2 昂貴。
- 無論評級為何，**PB < 1** 一律加註「股價低於淨值」小標籤，提醒使用者留意。
- 「其他」「綜合」等組成較雜的產業，畫面上一併顯示樣本數 `n`，讓使用者自行判斷可信度。
- 門檻（25% / 75% / 最少樣本數 5 / 絕對門檻 1 與 2）集中定義為常數，日後調整只需改一處。

### 3.2 第二階段：自身歷史區間評級（股價淨值比法）

以個股自己過去 5 年的 PB 分布為基準，比較貼近「河流圖」的看法：

- 便宜價 = 每股淨值 × 近 5 年 PB 低檔（第 10 百分位）
- 合理價 = 每股淨值 × 近 5 年 PB 中位數
- 昂貴價 = 每股淨值 × 近 5 年 PB 高檔（第 90 百分位）
- 收盤價 ≤ 便宜價 → 便宜；≥ 昂貴價 → 昂貴；其餘普通。
- 歷史資料不足 3 年的個股，退回第一階段的產業相對評級。

歷史 PB 改採 **每月取樣一天**（每月最後一個交易日），5 年只需 60 次請求／市場，
相較逐日回補（約 1,200 次／市場）少 95%，對分位數的估計影響很小。

## 4. 資料來源

| 用途 | 上市（TWSE） | 上櫃（TPEX） | 更新頻率 |
|---|---|---|---|
| 每股淨值（第一階段） | `openapi.twse.com.tw/v1/opendata/t187ap07_L_*`（資產負債表，含「每股參考淨值」） | `www.tpex.org.tw/openapi/v1/mopsfin_t187ap07_O_*` | 季 |
| 歷史 PB（第二階段） | `www.twse.com.tw/rwd/zh/afterTrading/BWIBBU_d`（全部上市股票當日本益比、殖利率、股價淨值比） | TPEX 個股本益比、殖利率及股價淨值比（依日期查詢） | 日（取樣用月） |

注意事項：

- 資產負債表依產業格式分成多支端點（一般業、金融、證券、保險、金控、其他），要全部抓完再合併。
- 這些端點在規劃時尚未實測（開發環境網路受限），實作第一步就是以真實資料存成 `tests/fixtures/`，
  欄位名稱以實測為準。
- 季報公告有時間差（Q3 財報最晚 11/14 公告），同一時間點不同公司的最新季別可能不同，
  所以每檔各自取「自己的最新一季」，與 `screen.py` 的 `_latest_per_stock` 同樣的道理。

## 5. 資料庫設計

新增一張表（Alembic migration）：

```text
book_values
  id          BIGSERIAL PK
  stock_code  VARCHAR(10)   NOT NULL
  period      DATE          NOT NULL   -- 季底日：2026-09-30 代表 2026Q3
  bvps        NUMERIC(10,2) NOT NULL   -- 每股參考淨值（元），可為負
  created_at  TIMESTAMP
  UNIQUE (stock_code, period)          -- upsert 冪等，與其他時序表一致
  INDEX  (stock_code, period DESC)     -- 取每檔最新一季
```

PB 與評級 **不落地**，查詢時即時計算：收盤價每天變、淨值每季變，存下來反而要處理過期問題。
全市場約 1,900 檔，一次查詢內完成排序與分組，成本可以忽略。

第二階段再新增 `pb_history (stock_code, trade_date, pb_ratio)`，只存每月取樣點。

## 6. 後端

### 6.1 爬蟲與 Pipeline

- 新增 `scraper/fundamental_scraper.py`：抓兩市資產負債表，輸出 `code, period, bvps`。
- `data_pipeline.run_full_pipeline()`（週末執行）加入淨值抓取與 `upsert_book_values()`。
  季資料一週抓一次已足夠，每日行情 pipeline 不需變動。
- 新增 `scripts/backfill_book_values.py`：上線時手動執行一次，不必等週末。

### 6.2 估值計算（單一 SQL）

```sql
WITH bv AS (               -- 每檔最新一季淨值
  SELECT DISTINCT ON (stock_code) stock_code, period, bvps
  FROM book_values ORDER BY stock_code, period DESC
), q AS (                  -- 每檔最新收盤
  SELECT DISTINCT ON (stock_code) stock_code, close
  FROM daily_quotes ORDER BY stock_code, trade_date DESC
), pb AS (
  SELECT s.code, s.industry, bv.bvps, bv.period, q.close,
         q.close / NULLIF(bv.bvps, 0) AS pb
  FROM stocks s JOIN bv ON bv.stock_code = s.code
                JOIN q  ON q.stock_code  = s.code
  WHERE bv.bvps > 0
), ind AS (                -- 產業中位數與樣本數（PERCENTILE_CONT 不能當視窗函式，需另外 GROUP BY）
  SELECT industry,
         PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY pb) AS ind_median,
         COUNT(*)                                        AS ind_n
  FROM pb GROUP BY industry
)
SELECT pb.*, ind.ind_median, ind.ind_n,
       PERCENT_RANK() OVER (PARTITION BY pb.industry ORDER BY pb.pb) AS ind_pct
FROM pb JOIN ind USING (industry);
```

- 時間複雜度 O(N log N)（N ≈ 1,900，排序由資料庫完成），空間 O(N)，沒有 N+1 查詢。
- `DISTINCT ON` 搭配 `(stock_code, period DESC)` 索引，取最新一季只需走索引。
- 評級判定寫成純函式 `rate_pb(pb, ind_pct, ind_n) -> "cheap" | "fair" | "expensive" | None`，方便單元測試。

### 6.3 API

| 端點 | 變更 |
|---|---|
| `GET /api/screen` | `ScreenItem` 新增 `bvps`、`bvps_period`、`pb_ratio`、`pb_rating`、`industry_pb_median`、`industry_pb_pct`、`industry_n`；新增查詢參數 `pb_ratings`（可複選，篩出指定評級） |
| `GET /api/valuation/industry` | **新增**。參數 `industry`（必填）、`codes`（選填，帶入時只回傳這些股票）。回傳該產業每檔的收盤、淨值、PB、評級，以及產業中位數、樣本數，依 PB 由低到高排序 |
| `GET /api/stocks/{code}` | `StockDetail` 一併帶出淨值、PB 與評級 |

## 7. 前端

1. **篩選結果表格**（`DashboardPage.tsx`）新增三欄：
   - 每股淨值（滑鼠移上顯示財報季別，例如「2026 Q3」）
   - PB（可排序）
   - 評級標籤：便宜（綠）／普通（灰）／昂貴（橘）。
     刻意不用紅綠：台股慣例紅漲綠跌，用紅色表示昂貴容易誤讀。
2. **篩選列**新增評級複選（便宜／普通／昂貴），與現有市場切換同樣的樣式。
3. **同產業比較**：點擊表格中的產業標籤，開啟側邊面板：
   - 切換「只看篩選結果內」／「全市場同產業」；
   - 依 PB 由低到高的橫條圖，標出產業中位數參考線，目前點選的股票以高亮顯示；
   - 下方表格列出代號、名稱、收盤、淨值、PB、百分位、評級。
4. CSV 匯出加入淨值、PB、評級三欄。

## 8. 測試

- 解析器：以實測回應存成 fixture，驗證兩市各產業格式都能取出 `bvps` 與季別。
- `rate_pb`：邊界值（剛好 25% / 75%、樣本 4 檔與 5 檔、淨值為負、PB < 1 加註）。
- API：沿用 `test_api_offline.py` 的方式，驗證 `/api/screen` 新欄位與 `/api/valuation/industry`。
- Migration：`verify_migration_schema.py` 確認新表與模型一致。

## 9. 工作拆分與估時

| # | 項目 | 估時 |
|---|---|---|
| 1 | 實測端點、存 fixture、寫解析器 | 2h |
| 2 | `book_values` 模型 + migration + upsert + 回補腳本 | 1.5h |
| 3 | 估值 SQL、`rate_pb`、`/api/screen` 擴充、`/api/valuation/industry` | 2.5h |
| 4 | 前端表格欄位、評級篩選、CSV | 2h |
| 5 | 同產業比較面板（含橫條圖） | 2.5h |
| 6 | 測試與文件 | 1.5h |
| | **第一階段合計** | **約 12h** |
| 7 | 第二階段：歷史 PB 月取樣回補、`pb_history`、便宜價／合理價／昂貴價、個股河流圖 | 約 8h |

## 10. 待確認事項

1. 評級基準：第一階段採「同產業相對」是否同意？還是要先用絕對門檻（PB < 1 / 1–2 / > 2）？
2. 同產業比較的預設範圍：「全市場同產業」或「只看篩選結果內」？
3. 是否要接著做第二階段（自身歷史區間與便宜價／昂貴價）？
4. 參考文章若有指定的門檻或公式，請提供重點段落，以文章為準調整第 3 節。
