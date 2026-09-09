"""
回歸測試：TWSE 當日行情改用官網 afterTrading/MI_INDEX（2026-09-10 修復）。

根因：
  舊版 fetch_all_quotes() 打 openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL，
  這支 TWSE OpenAPI **固定只提供前一交易日的資料**（社群已知行為，非暫時延遲），
  所以上市股票的收盤價永遠比上櫃（TPEX）慢一天。
  三大法人（T86）之所以一直是對的，正是因為它走 www.twse.com.tw 官網 API。

  實測證據（2026-09-09 / 09-10）：9/9 收盤後 18:00 跑、23:12 再跑、
  隔天凌晨再打一次，STOCK_DAY_ALL 回報的都還是 9/8；
  同一時間用 MI_INDEX 查 date=20260909 就直接拿得到 9/9 的資料。

  修法：改打 afterTrading/MI_INDEX，交易日仍從 payload 的表格標題解析
  （不是 date.today()），維持 P0-2 的原則。
"""
from datetime import date

import pytest

from scraper import twse_scraper as tw


# ── 表格標題的交易日解析 ──────────────────────────────────────
def test_parse_title_date_from_real_mi_index_table():
    """MI_INDEX 表格 title 是「115年09月09日 每日收盤行情(...)」，要能解析出 2026-09-09"""
    title = "115年09月09日 每日收盤行情(全部(不含權證、牛熊證、可展延牛熊證))"
    assert tw._parse_title_date(title) == date(2026, 9, 9)


def test_parse_title_date_returns_none_on_garbage():
    for bad in ["", "沒有日期的標題", None, "115年13月40日"]:
        assert tw._parse_title_date(bad) is None


# ── 主要路徑：當天就拿到當天的資料 ────────────────────────────
async def test_fetch_all_quotes_uses_mi_index_and_gets_same_day_data(fx, monkeypatch):
    """
    核心回歸測試：給定 MI_INDEX 的真實樣本，解析出的 trade_date 必須等於
    payload 標題裡的日期（= 查詢當天），而不是任何「前一天」的值——
    這正是舊版 STOCK_DAY_ALL 的 bug。
    """
    payload = fx.json("twse_mi_index.json")
    seen_urls = []

    async def fake_fetch_json(client, url, params=None):
        seen_urls.append(url)
        return payload

    monkeypatch.setattr(tw, "fetch_json", fake_fetch_json)

    df = await tw.fetch_all_quotes(client=None, target=date(2026, 9, 9))

    assert seen_urls, "應該真的發出請求"
    assert all("afterTrading/MI_INDEX" in u for u in seen_urls), \
        "必須打官網 MI_INDEX，不能退回 openapi 的 STOCK_DAY_ALL"
    assert (df["trade_date"] == date(2026, 9, 9)).all()

    # 00400A 是 ETF（非 4 碼股票代號），必須被濾掉
    assert set(df["code"]) == {"2330", "2454"}

    row = df[df["code"] == "2330"].iloc[0]
    assert row["close"] == pytest.approx(1100.00)
    assert row["open"] == pytest.approx(1095.00)
    assert row["market"] == "TWSE"
    assert row["volume"] == 18235          # 18,234,567 股 ÷ 1000，四捨五入


async def test_fetch_all_quotes_on_returns_empty_for_non_trading_day(monkeypatch):
    """指定日期版本：非交易日回空 DataFrame，不 raise、不往前找"""
    async def fake_fetch_json(client, url, params=None):
        return {"stat": "很抱歉，沒有符合條件的資料!"}

    monkeypatch.setattr(tw, "fetch_json", fake_fetch_json)

    df = await tw.fetch_all_quotes_on(client=None, target=date(2026, 9, 6))  # 週日
    assert df.empty
    assert list(df.columns) == tw.QUOTE_COLUMNS


# ── 假日往前找：週末排程不能因為改端點而抓不到行情 ────────────
async def test_fetch_all_quotes_walks_back_to_last_trading_day(fx, monkeypatch):
    """
    回歸測試：MI_INDEX 是「查某一天」的 API，假日查不到資料。
    但週六 10:00 的完整 pipeline 需要最近一個交易日的行情——
    舊的 STOCK_DAY_ALL 天生就回最近交易日快照，換端點時不能弄丟這個行為。
    """
    payload = fx.json("twse_mi_index.json")   # 標題是 9/9（週三）
    asked = []

    async def fake_fetch_json(client, url, params=None):
        asked.append(params["date"])
        # 只有 9/9 有資料，9/12(六)、9/11(五)、9/10(四) 都當作沒有
        return payload if params["date"] == "20260909" else {"stat": "無資料"}

    monkeypatch.setattr(tw, "fetch_json", fake_fetch_json)

    df = await tw.fetch_all_quotes(client=None, target=date(2026, 9, 12))  # 週六

    assert asked == ["20260912", "20260911", "20260910", "20260909"]
    assert not df.empty
    assert (df["trade_date"] == date(2026, 9, 9)).all(), \
        "往前找到的資料，日期必須標成 payload 裡的 9/9，不能標成查詢起點 9/12"


async def test_fetch_all_quotes_gives_up_after_lookback_window(monkeypatch):
    """長假或 API 掛掉：找滿 lookback 天數就放棄，回空 DataFrame（呼叫端會中止寫入）"""
    calls = 0

    async def fake_fetch_json(client, url, params=None):
        nonlocal calls
        calls += 1
        return {"stat": "無資料"}

    monkeypatch.setattr(tw, "fetch_json", fake_fetch_json)

    df = await tw.fetch_all_quotes(client=None, target=date(2026, 9, 12))
    assert df.empty
    assert calls == tw.QUOTE_LOOKBACK_DAYS


async def test_fetch_all_quotes_on_raises_when_title_has_no_date(monkeypatch):
    """有收盤行情表、卻解析不出日期時要 raise——絕不用今天的日期硬寫進時序表"""
    async def fake_fetch_json(client, url, params=None):
        return {"tables": [{
            "title": "每日收盤行情",           # 沒有民國日期
            "fields": ["證券代號", "收盤價"],
            "data": [["2330", "1100.00"]],
        }]}

    monkeypatch.setattr(tw, "fetch_json", fake_fetch_json)

    with pytest.raises(ValueError, match="拒絕以今日日期寫入"):
        await tw.fetch_all_quotes_on(client=None, target=date(2026, 9, 9))
