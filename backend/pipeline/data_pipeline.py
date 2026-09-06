"""
StockRadar - 資料清洗 / 合併 / 寫入 PostgreSQL Pipeline
執行順序：
  1. run_twse_pipeline()  → TWSE 行情 + 法人
  2. run_tpex_pipeline()  → TPEX 行情 + 法人
  3. merge_markets()      → 合併上市上櫃，計算 20 日均量
  4. filter_candidates()  → 篩出均量 >= 2000 張的候選股
  5. fetch_chip_batch()   → 只抓候選股的集保籌碼
  6. final_screen()       → 最終篩選（均量 + 籌碼集中度）
  7. upsert_all()         → 寫入 PostgreSQL
"""
import asyncio
import logging
from datetime import date, datetime
from typing import Optional

import httpx
import pandas as pd
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from models.database import AsyncSessionLocal, DailyQuote, InstitutionalFlow, ChipConcentration, Stock
from scraper.twse_scraper import (
    run_twse_pipeline,
    fetch_all_quotes as twse_fetch_quotes,
    fetch_institutional_flow_on as twse_inst_on,
    HEADERS as TWSE_HEADERS,
)
from scraper.tpex_scraper import (
    run_tpex_pipeline,
    fetch_all_quotes as tpex_fetch_quotes,
    fetch_institutional_flow_on as tpex_inst_on,
    HEADERS as TPEX_HEADERS,
)
from scraper.tdcc_scraper import fetch_chip_batch
from scraper.ownership_scraper import run_ownership_pipeline

logger = logging.getLogger(__name__)

MIN_AVG_VOL   = 2000   # 日均量門檻（張）
MIN_CHIP_CONC = 40.0   # 籌碼集中度門檻（%）
AVG_VOL_DAYS  = 20     # 均量計算天數（近 N 個有開盤的交易日）


def _row_trade_date(row, fallback: Optional[date]) -> date:
    """
    取一列的交易日：優先用 scraper 從 payload 解析出的 row["trade_date"]，
    沒有才用呼叫端指定的 fallback；兩者皆無就 raise，絕不默默用今日日期。
    """
    v = row.get("trade_date")
    if v is None or pd.isna(v):
        if fallback is None:
            raise ValueError(f"[DB] {row.get('code') or row.get('stock_code')} 缺少 trade_date")
        return fallback
    return v.date() if isinstance(v, (pd.Timestamp, datetime)) else v


# ── 0. 從 DB 計算近 N 日均量 ─────────────────────────────────
async def compute_avg_vol_from_db(codes: list[str]) -> dict[str, float]:
    """
    從 daily_quotes 取各股最近 AVG_VOL_DAYS 個有交易日的均量（張）。
    只計算 volume > 0 的列（排除停牌日），讓「近20個有開盤日」更準確。
    回傳 {stock_code: avg_vol_20d}；DB 無歷史的股票不出現在結果裡。
    """
    if not codes:
        return {}
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            text("""
                SELECT stock_code,
                       ROUND(AVG(volume)::numeric, 1) AS avg_vol
                FROM (
                    SELECT stock_code, volume,
                           ROW_NUMBER() OVER (
                               PARTITION BY stock_code
                               ORDER BY trade_date DESC
                           ) AS rn
                    FROM daily_quotes
                    WHERE stock_code = ANY(:codes)
                      AND volume > 0
                ) t
                WHERE rn <= :days
                GROUP BY stock_code
            """),
            {"codes": list(codes), "days": AVG_VOL_DAYS},
        )
        rows = result.fetchall()
    avg_map = {row.stock_code: float(row.avg_vol) for row in rows}
    logger.info(
        f"[Pipeline] DB 均量：取得 {len(avg_map)}/{len(codes)} 檔 "
        f"（近{AVG_VOL_DAYS}個交易日）"
    )
    return avg_map


# ── 1. 合併上市 + 上櫃行情 ────────────────────────────────────
def merge_markets(twse: dict, tpex: dict) -> pd.DataFrame:
    """
    合併 TWSE / TPEX 行情，統一欄位格式
    回傳：code, name, market, trade_date, open, high, low, close, volume, avg_vol_20d
    """
    frames = []

    if not twse["quotes"].empty:
        df_t = twse["quotes"].copy()
        # 補入公司資料（產業）
        if not twse["companies"].empty:
            company_map = twse["companies"].set_index("code")[["industry"]].to_dict("index")
            df_t["industry"] = df_t["code"].map(
                lambda c: company_map.get(c, {}).get("industry", "其他")
            )
        # 補入 avg_vol_20d
        avg_map = {
            row["code"]: row["avg_vol_20d"]
            for _, row in df_t.iterrows()
            if "avg_vol_20d" in df_t.columns
        }
        frames.append(df_t)

    if not tpex["quotes"].empty:
        df_p = tpex["quotes"].copy()
        if not tpex["companies"].empty:
            company_map = tpex["companies"].set_index("code")[["industry"]].to_dict("index")
            df_p["industry"] = df_p["code"].map(
                lambda c: company_map.get(c, {}).get("industry", "其他")
            )
        frames.append(df_p)

    if not frames:
        return pd.DataFrame()

    merged = pd.concat(frames, ignore_index=True)
    merged = merged.drop_duplicates(subset=["code"])

    logger.info(f"[Pipeline] 合併後總計：{len(merged)} 檔（上市 + 上櫃）")
    return merged


# ── 2. 篩出候選股（均量門檻） ─────────────────────────────────
def filter_candidates(df: pd.DataFrame) -> list[str]:
    """
    回傳日均量 >= MIN_AVG_VOL 的股票代號清單
    若 avg_vol_20d 無資料，以當日 volume 替代（保守估計）
    """
    if "avg_vol_20d" in df.columns:
        vol_col = df["avg_vol_20d"].fillna(df["volume"])
    else:
        vol_col = df["volume"]

    candidates = df[vol_col >= MIN_AVG_VOL]["code"].tolist()
    logger.info(f"[Pipeline] 均量≥{MIN_AVG_VOL}張候選股：{len(candidates)} 檔")
    return candidates


# ── 3. 最終篩選（均量 + 籌碼集中度） ─────────────────────────
def final_screen(
    quotes_df: pd.DataFrame,
    chip_data: list[dict],
) -> pd.DataFrame:
    """
    合併行情與籌碼資料，套用雙重篩選條件，回傳結果 DataFrame
    """
    if not chip_data:
        logger.warning("[Pipeline] 無籌碼資料，跳過最終篩選")
        return pd.DataFrame()

    chip_df = pd.DataFrame(chip_data)

    # 確保均量欄位存在且無 NaN
    # TWSE STOCK_DAY 個股歷史 API 可能失效，此時 avg_vol_20d 全為 NaN，
    # 用當日量 (volume) 做 fallback，並記 warning 提醒
    if "avg_vol_20d" not in quotes_df.columns:
        quotes_df["avg_vol_20d"] = quotes_df["volume"]
        logger.warning("[Pipeline] avg_vol_20d 欄位不存在，改用當日成交量代替")
    elif quotes_df["avg_vol_20d"].isna().all():
        quotes_df["avg_vol_20d"] = quotes_df["volume"]
        logger.warning("[Pipeline] avg_vol_20d 全為 NaN（個股歷史 API 失效），改用當日成交量代替")
    else:
        # 部分 NaN 時，個別 fallback
        nan_mask = quotes_df["avg_vol_20d"].isna()
        quotes_df.loc[nan_mask, "avg_vol_20d"] = quotes_df.loc[nan_mask, "volume"]

    merged = quotes_df.merge(
        chip_df[["stock_code", "conc_ratio", "holders_400up", "holders_total"]],
        left_on="code", right_on="stock_code", how="inner"
    )

    result = merged[
        (merged["avg_vol_20d"] >= MIN_AVG_VOL) &
        (merged["conc_ratio"]  >= MIN_CHIP_CONC)
    ].copy()

    result = result.sort_values("conc_ratio", ascending=False)

    logger.info(
        f"[Pipeline] 🎯 最終篩選結果：{len(result)} 檔\n"
        f"           條件：均量≥{MIN_AVG_VOL}張 且 籌碼集中度≥{MIN_CHIP_CONC}%"
    )
    return result


# ── 4. Upsert 行情到 PostgreSQL ───────────────────────────────
async def upsert_daily_quotes(
    session: AsyncSession,
    df: pd.DataFrame,
    trade_date: Optional[date] = None,
) -> int:
    """upsert daily_quotes，回傳寫入筆數"""
    if df.empty:
        return 0

    # P0-2：以前這裡一律 date.today()，把 scraper 算好的交易日整個蓋掉，
    # 週末跑就寫進週六/週日的假日期。現在逐列尊重 row["trade_date"]。
    has_row_dates = "trade_date" in df.columns and df["trade_date"].notna().any()
    if trade_date is None and not has_row_dates:
        logger.warning("[DB] daily_quotes 無 trade_date 可用，fallback 今日日期（可能非交易日！）")
        trade_date = date.today()
    count = 0

    for _, row in df.iterrows():
        await session.execute(
            text("""
                INSERT INTO daily_quotes
                    (stock_code, trade_date, open, high, low, close, volume, avg_vol_20d)
                VALUES
                    (:code, :date, :open, :high, :low, :close, :vol, :avg)
                ON CONFLICT (stock_code, trade_date)
                DO UPDATE SET
                    close       = EXCLUDED.close,
                    volume      = EXCLUDED.volume,
                    avg_vol_20d = EXCLUDED.avg_vol_20d,
                    open        = EXCLUDED.open,
                    high        = EXCLUDED.high,
                    low         = EXCLUDED.low
            """),
            {
                "code":  row["code"],
                "date":  _row_trade_date(row, trade_date),
                "open":  _safe_float(row.get("open")),
                "high":  _safe_float(row.get("high")),
                "low":   _safe_float(row.get("low")),
                "close": _safe_float(row.get("close")),
                "vol":   _safe_int(row.get("volume")),
                "avg":   _safe_float(row.get("avg_vol_20d")),
            }
        )
        count += 1

    await session.commit()
    logger.info(f"[DB] daily_quotes upsert：{count} 筆")
    return count


# ── 5. Upsert 法人資料 ────────────────────────────────────────
async def upsert_institutional_flow(
    session: AsyncSession,
    df: pd.DataFrame,
) -> int:
    if df.empty:
        return 0

    count = 0
    for _, row in df.iterrows():
        await session.execute(
            text("""
                INSERT INTO institutional_flow
                    (stock_code, trade_date, foreign_net, trust_net, dealer_net, total_net)
                VALUES
                    (:code, :date, :foreign, :trust, :dealer, :total)
                ON CONFLICT (stock_code, trade_date)
                DO UPDATE SET
                    foreign_net = EXCLUDED.foreign_net,
                    trust_net   = EXCLUDED.trust_net,
                    dealer_net  = EXCLUDED.dealer_net,
                    total_net   = EXCLUDED.total_net
            """),
            {
                "code":    row["code"],
                "date":    _row_trade_date(row, None),
                "foreign": _safe_int(row.get("foreign_net")),
                "trust":   _safe_int(row.get("trust_net")),
                "dealer":  _safe_int(row.get("dealer_net")),
                "total":   _safe_int(row.get("total_net")),
            }
        )
        count += 1

    await session.commit()
    logger.info(f"[DB] institutional_flow upsert：{count} 筆")
    return count


# ── 6. Upsert 籌碼集中度 ─────────────────────────────────────
async def upsert_chip_concentration(
    session: AsyncSession,
    chip_data: list[dict],
) -> int:
    if not chip_data:
        return 0

    count = 0
    for row in chip_data:
        await session.execute(
            text("""
                INSERT INTO chip_concentration
                    (stock_code, week_date, holders_400up, holders_total, shares_400up, conc_ratio)
                VALUES
                    (:code, :week, :h400, :htotal, :s400, :ratio)
                ON CONFLICT (stock_code, week_date)
                DO UPDATE SET
                    holders_400up = EXCLUDED.holders_400up,
                    holders_total = EXCLUDED.holders_total,
                    shares_400up  = EXCLUDED.shares_400up,
                    conc_ratio    = EXCLUDED.conc_ratio
            """),
            {
                "code":   row["stock_code"],
                "week":   row["week_date"],
                "h400":   row.get("holders_400up"),
                "htotal": row.get("holders_total"),
                "s400":   row.get("shares_400up"),
                "ratio":  row.get("conc_ratio"),
            }
        )
        count += 1

    await session.commit()
    logger.info(f"[DB] chip_concentration upsert：{count} 筆")
    return count


# ── 7. Upsert 持股比例 ───────────────────────────────────────
async def upsert_ownership_ratios(
    session: AsyncSession,
    rows: list[dict],
) -> int:
    """
    upsert ownership_ratios（外資 / 投信 / 董監事持股比例）

    rows: list[dict]，每筆含
        stock_code, report_date, foreign_hold_ratio, director_hold_ratio, trust_hold_ratio
    """
    if not rows:
        return 0

    count = 0
    for row in rows:
        await session.execute(
            text("""
                INSERT INTO ownership_ratios
                    (stock_code, report_date, foreign_hold_ratio, trust_hold_ratio, director_hold_ratio)
                VALUES
                    (:code, :date, :foreign, :trust, :director)
                ON CONFLICT (stock_code, report_date)
                DO UPDATE SET
                    foreign_hold_ratio  = COALESCE(EXCLUDED.foreign_hold_ratio,  ownership_ratios.foreign_hold_ratio),
                    trust_hold_ratio    = COALESCE(EXCLUDED.trust_hold_ratio,    ownership_ratios.trust_hold_ratio),
                    director_hold_ratio = COALESCE(EXCLUDED.director_hold_ratio, ownership_ratios.director_hold_ratio)
            """),
            {
                "code":     row["stock_code"],
                "date":     row["report_date"],
                "foreign":  _safe_float(row.get("foreign_hold_ratio")),
                "trust":    _safe_float(row.get("trust_hold_ratio")),
                "director": _safe_float(row.get("director_hold_ratio")),
            }
        )
        count += 1

    await session.commit()
    logger.info(f"[DB] ownership_ratios upsert：{count} 筆")
    return count


# ── 8. Upsert 股票基本資料 ────────────────────────────────────
async def upsert_stocks(
    session: AsyncSession,
    companies_df: pd.DataFrame,
    market: str,
) -> int:
    if companies_df.empty:
        return 0

    count = 0
    for _, row in companies_df.iterrows():
        await session.execute(
            text("""
                INSERT INTO stocks (code, name, short_name, market, industry)
                VALUES (:code, :name, :short_name, :market, :industry)
                ON CONFLICT (code)
                DO UPDATE SET
                    name       = EXCLUDED.name,
                    short_name = COALESCE(NULLIF(EXCLUDED.short_name, ''), stocks.short_name),
                    industry   = COALESCE(NULLIF(EXCLUDED.industry, '其他'), stocks.industry, '其他')
            """),
            {
                "code":       row.get("code", ""),
                "name":       row.get("name", ""),
                "short_name": row.get("short_name") or None,
                "market":     market,
                "industry":   row.get("industry", "其他"),
            }
        )
        count += 1

    await session.commit()
    logger.info(f"[DB] stocks upsert ({market})：{count} 筆")
    return count


# ── 主流程 ────────────────────────────────────────────────────
async def run_full_pipeline() -> dict:
    """
    完整資料 Pipeline：
      抓取 → 合併 → 篩選 → 寫 DB → 回傳結果
    """
    logger.info("🚀 StockRadar Pipeline 開始執行")
    logger.info("=" * 60)

    # ① 並行抓取 TWSE + TPEX
    twse_result, tpex_result = await asyncio.gather(
        run_twse_pipeline(),
        run_tpex_pipeline(),
    )

    # ② 合併行情
    all_quotes = merge_markets(twse_result, tpex_result)

    # ③ 從 DB 計算近20個交易日均量，覆蓋 scraper 的 avg_vol_20d
    #    TWSE 個股歷史 API 已失效，改用 daily_quotes 累積的歷史資料。
    #    初次執行 DB 為空時，fallback 到當日 volume（final_screen 內處理）。
    all_codes = all_quotes["code"].tolist()
    db_avg_map = await compute_avg_vol_from_db(all_codes)
    if db_avg_map:
        all_quotes["avg_vol_20d"] = all_quotes["code"].map(db_avg_map)
        logger.info(f"[Pipeline] 已套用 DB 均量（覆蓋 scraper 值）")
    else:
        logger.warning("[Pipeline] DB 無均量歷史，本次以當日 volume 代替")

    # ④ 篩出均量候選股
    candidates = filter_candidates(all_quotes)
    if not candidates:
        logger.warning("⚠️ 沒有符合均量條件的候選股")
        return {"screened": pd.DataFrame(), "total": 0}

    # ④ 並行：抓集保籌碼 + HiStock 持股比例
    #    集保：只抓候選股（節省時間），week_date=None 自動讀最新已發布日期
    #    HiStock：外資籌碼 + 董監持股，同樣只抓候選股
    chip_data, ownership_rows = await asyncio.gather(
        fetch_chip_batch(candidates, week_date=None, min_conc=MIN_CHIP_CONC),
        run_ownership_pipeline(candidates),
    )

    # ⑤ 最終篩選
    screened = final_screen(all_quotes, chip_data)

    # ⑥ 寫入 PostgreSQL
    # TPEX 公司 API 可能失效，改用 quotes 的 code+name 做 fallback
    tpex_companies = tpex_result["companies"]
    if tpex_companies.empty and not tpex_result["quotes"].empty:
        logger.warning("[Pipeline] TPEX 公司 API 失效，改用行情資料的 code/name 建立 stocks 記錄")
        tpex_companies = (
            tpex_result["quotes"][["code", "name"]]
            .drop_duplicates("code")
            .assign(industry="其他", short_name=None)
        )

    async with AsyncSessionLocal() as session:
        await upsert_stocks(session, twse_result["companies"], "TWSE")
        await upsert_stocks(session, tpex_companies, "TPEX")
        await upsert_daily_quotes(session, all_quotes)
        await upsert_institutional_flow(session, twse_result["inst_flow"])
        await upsert_institutional_flow(session, tpex_result["inst_flow"])
        await upsert_chip_concentration(session, chip_data)
        # 持股比例（外資持股 / 董監持股）：HiStock 來源
        if ownership_rows:
            await upsert_ownership_ratios(session, ownership_rows)

    logger.info("=" * 60)
    logger.info(f"✅ Pipeline 完成！最終篩選結果：{len(screened)} 檔")

    return {
        "screened":        screened,
        "total":           len(all_quotes),
        "candidates":      len(candidates),
        "chip_count":      len(chip_data),
        "ownership_count": len(ownership_rows),
    }


async def refresh_avg_vol(session: AsyncSession, trade_date: date) -> int:
    """
    以單一 SQL 重算「指定交易日」那批列的 20 日均量。

    比起先算好再逐列 upsert，這樣做有兩個好處：
      1. 今天的成交量本身也會被算進 20 日均量（先寫入再重算）
      2. 一個 statement 取代 ~2000 次 round-trip
    """
    result = await session.execute(
        text("""
            WITH avg20 AS (
                SELECT stock_code, ROUND(AVG(volume)::numeric, 1) AS av
                FROM (
                    SELECT stock_code, volume,
                           ROW_NUMBER() OVER (
                               PARTITION BY stock_code ORDER BY trade_date DESC
                           ) AS rn
                    FROM daily_quotes
                    WHERE volume > 0
                ) t
                WHERE rn <= :days
                GROUP BY stock_code
            )
            UPDATE daily_quotes q
            SET avg_vol_20d = a.av
            FROM avg20 a
            WHERE q.stock_code = a.stock_code
              AND q.trade_date = :td
        """),
        {"days": AVG_VOL_DAYS, "td": trade_date},
    )
    await session.commit()
    logger.info(f"[DB] 重算 {trade_date} 的 20 日均量：{result.rowcount} 筆")
    return result.rowcount


# ── 交易日盤後 Pipeline（每日排程） ───────────────────────────
async def run_quotes_pipeline() -> dict:
    """
    交易日盤後模式：只更新「每天會變」的資料。
      ① TWSE / TPEX 當日行情            → daily_quotes
      ② 兩市三大法人買賣超（指定交易日）→ institutional_flow
      ③ 以 SQL 重算該交易日的 20 日均量

    刻意不碰 TDCC 集保籌碼與 HiStock 持股比例：那是**每週**更新的資料，
    每天去抓 500+ 檔既拿不到新資訊，對來源也不禮貌 —— 交給週末的完整 pipeline。

    非交易日執行是安全的：兩個行情 API 都回「最近一個交易日」的快照，
    trade_date 取自 payload（不是 date.today()），因此只是把同一天的資料
    再 upsert 一次，冪等、不會污染時序表。
    """
    logger.info("📈 StockRadar 交易日行情 Pipeline 開始")
    logger.info("=" * 60)

    async with httpx.AsyncClient(headers=TWSE_HEADERS, follow_redirects=True) as tc, \
               httpx.AsyncClient(headers=TPEX_HEADERS, follow_redirects=True) as pc:

        twse_q, tpex_q = await asyncio.gather(
            twse_fetch_quotes(tc),
            tpex_fetch_quotes(pc),
        )

        frames = [df for df in (twse_q, tpex_q) if not df.empty]
        if not frames:
            logger.error("[Daily] 兩市行情皆為空，中止（不寫入任何資料）")
            return {"total": 0, "inst": 0, "trade_date": None}

        all_quotes = pd.concat(frames, ignore_index=True).drop_duplicates(subset=["code"])

        # 各市場的交易日各自取自 payload，通常相同但不強制假設
        twse_date = twse_q["trade_date"].iloc[0] if not twse_q.empty else None
        tpex_date = tpex_q["trade_date"].iloc[0] if not tpex_q.empty else None
        trade_date = twse_date or tpex_date
        logger.info(f"[Daily] 行情 {len(all_quotes)} 檔，交易日 TWSE={twse_date} TPEX={tpex_date}")

        # ② 三大法人：用行情回報的交易日去要，確保兩張表日期一致
        tasks, labels = [], []
        if twse_date:
            tasks.append(twse_inst_on(tc, twse_date)); labels.append("TWSE")
        if tpex_date:
            tasks.append(tpex_inst_on(pc, tpex_date)); labels.append("TPEX")
        inst_frames = list(await asyncio.gather(*tasks)) if tasks else []

    for label, df in zip(labels, inst_frames):
        logger.info(f"[Daily] {label} 三大法人：{len(df)} 筆")

    # ③ 寫入
    async with AsyncSessionLocal() as session:
        await upsert_daily_quotes(session, all_quotes)
        await refresh_avg_vol(session, trade_date)
        for df in inst_frames:
            if not df.empty:
                await upsert_institutional_flow(session, df)

    inst_total = sum(len(df) for df in inst_frames)
    logger.info("=" * 60)
    logger.info(f"✅ 行情 Pipeline 完成：{len(all_quotes)} 檔行情、{inst_total} 筆法人（{trade_date}）")

    return {"total": len(all_quotes), "inst": inst_total, "trade_date": trade_date}


# ── 非交易日 Pipeline ─────────────────────────────────────────
async def run_offline_pipeline() -> dict:
    """
    非交易日模式（週末 / 假日 / 盤後手動觸發）：
      ① 不抓 TWSE / TPEX 當日行情（市場休市，API 回空）
      ② 從 DB 取最後一個交易日的行情 + 已算好的 avg_vol_20d
      ③ 過濾 avg_vol_20d >= MIN_AVG_VOL 的候選股
      ④ 重新抓集保籌碼（TDCC，週四更新）+ HiStock 持股比例
      ⑤ 寫回 DB —— /api/screen 自動反映最新籌碼
    """
    logger.info("🌙 StockRadar 非交易日 Pipeline 開始執行")
    logger.info("=" * 60)

    # ① 從 DB 取最新一個交易日的所有行情（含 avg_vol_20d）
    async with AsyncSessionLocal() as session:
        result = await session.execute(text("""
            SELECT dq.stock_code AS code,
                   s.name,
                   s.market,
                   s.industry,
                   dq.close,
                   dq.volume,
                   dq.avg_vol_20d,
                   dq.trade_date
            FROM daily_quotes dq
            JOIN stocks s ON s.code = dq.stock_code
            WHERE dq.trade_date = (SELECT MAX(trade_date) FROM daily_quotes)
              AND dq.volume > 0
        """))
        rows = result.fetchall()

    if not rows:
        logger.error("[Offline] DB 無行情資料，請先執行 backfill_history.py")
        return {"screened": pd.DataFrame(), "total": 0, "candidates": 0}

    all_quotes = pd.DataFrame(rows, columns=[
        "code", "name", "market", "industry", "close", "volume", "avg_vol_20d", "trade_date"
    ])
    trade_date = all_quotes["trade_date"].iloc[0]
    logger.info(f"[Offline] 從 DB 載入 {len(all_quotes)} 檔，最新交易日：{trade_date}")

    # ② 用 DB 均量重新計算（確保是近20日的值）
    all_codes  = all_quotes["code"].tolist()
    db_avg_map = await compute_avg_vol_from_db(all_codes)
    if db_avg_map:
        all_quotes["avg_vol_20d"] = all_quotes["code"].map(db_avg_map).fillna(all_quotes["avg_vol_20d"])

    # ③ 篩出候選股
    candidates = filter_candidates(all_quotes)
    if not candidates:
        logger.warning("⚠️ 沒有符合均量條件的候選股")
        return {"screened": pd.DataFrame(), "total": len(all_quotes), "candidates": 0}

    # ④ 並行：集保籌碼 + HiStock 持股比例
    logger.info(f"[Offline] 抓取 {len(candidates)} 檔候選股的籌碼 + 持股比例...")
    chip_data, ownership_rows = await asyncio.gather(
        fetch_chip_batch(candidates, week_date=None, min_conc=MIN_CHIP_CONC),
        run_ownership_pipeline(candidates),
    )

    # ⑤ 最終篩選（用 DB 行情 + 最新籌碼）
    screened = final_screen(all_quotes, chip_data)

    # ⑥ 寫回 DB
    async with AsyncSessionLocal() as session:
        await upsert_chip_concentration(session, chip_data)
        if ownership_rows:
            await upsert_ownership_ratios(session, ownership_rows)

    logger.info("=" * 60)
    logger.info(
        f"✅ 非交易日 Pipeline 完成！\n"
        f"   行情來源：DB（{trade_date}）\n"
        f"   候選股：{len(candidates)} 檔\n"
        f"   籌碼集中度≥{MIN_CHIP_CONC}%：{len(screened)} 檔\n"
        f"   外資/董監持股更新：{len(ownership_rows)} 筆"
    )

    return {
        "screened":        screened,
        "total":           len(all_quotes),
        "candidates":      len(candidates),
        "chip_count":      len(chip_data),
        "ownership_count": len(ownership_rows),
    }


# ── 工具函數 ──────────────────────────────────────────────────
def _safe_float(val) -> Optional[float]:
    try:
        return float(val) if val is not None and str(val) not in ("nan", "NaN", "") else None
    except (ValueError, TypeError):
        return None


def _safe_int(val) -> Optional[int]:
    try:
        return int(val) if val is not None and str(val) not in ("nan", "NaN", "") else None
    except (ValueError, TypeError):
        return None


if __name__ == "__main__":
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    # python -m pipeline.data_pipeline          → 完整 pipeline（行情 + 籌碼 + 持股）
    # python -m pipeline.data_pipeline quotes   → 交易日盤後：只更新行情 + 法人 + 均量
    # python -m pipeline.data_pipeline offline  → 非交易日：不抓行情，只更新籌碼 + 持股
    mode = sys.argv[1] if len(sys.argv) > 1 else "full"

    async def _run():
        if mode == "quotes":
            logger.info("▶ 交易日盤後模式（quotes）")
            result = await run_quotes_pipeline()
        elif mode == "offline":
            logger.info("▶ 非交易日模式（offline）")
            result = await run_offline_pipeline()
        else:
            result = await run_full_pipeline()

        screened = result.get("screened", pd.DataFrame())
        if not screened.empty:
            cols = ["code", "name", "market", "close", "avg_vol_20d", "conc_ratio",
                    "foreign_hold_ratio", "director_hold_ratio"]
            cols = [c for c in cols if c in screened.columns]
            print(f"\n🎯 最終篩選結果（{len(screened)} 檔）：")
            print(screened[cols].head(20).to_string(index=False))
        else:
            print("\n⚠️ 無篩選結果")

    asyncio.run(_run())
