"""
證交所請求太密時會斷線或回 307（限流）。這裡用模擬回應確認：
估值表與三大法人都會重試，重試成功就拿得到資料；一直失敗才回空表。
"""
from datetime import date

import httpx
import pytest

import scraper.twse_scraper as twse
import scraper.valuation as valuation

DAY = date(2026, 11, 6)


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    async def _skip(_):
        return None
    monkeypatch.setattr(twse.asyncio, "sleep", _skip)
    monkeypatch.setattr(valuation.asyncio, "sleep", _skip)


def _client(responses: list):
    """依序回傳 responses；元素是 Exception 就丟出，否則是 (status, json)"""
    calls = {"n": 0}

    def handler(request):
        item = responses[min(calls["n"], len(responses) - 1)]
        calls["n"] += 1
        if isinstance(item, Exception):
            raise item
        status, body = item
        return httpx.Response(status, json=body, headers={"location": "/"} if status == 307 else {})

    return httpx.AsyncClient(transport=httpx.MockTransport(handler)), calls


async def test_valuation_retries_after_throttle(fx):
    payload = fx.json("twse_bwibbu_20261106.json")
    client, calls = _client([(307, {}), httpx.ConnectError(""), (200, payload)])
    async with client:
        df = await valuation.fetch_twse_on(client, DAY)
    assert calls["n"] == 3
    assert len(df) == 18


async def test_valuation_gives_up_after_retries():
    client, calls = _client([httpx.ConnectError("")])
    async with client:
        df = await valuation.fetch_twse_on(client, DAY)
    assert calls["n"] == valuation.RETRY_COUNT
    assert df.empty


async def test_t86_retries_after_throttle(fx):
    payload = fx.json("t86_20260904.json")
    client, calls = _client([(307, {}), (200, payload)])
    async with client:
        df = await twse.fetch_institutional_flow_on(client, date(2026, 9, 4))
    assert calls["n"] == 2
    assert "2324" in df["code"].tolist()


async def test_t86_non_trading_day_is_not_retried():
    """非交易日回 200 + 沒有資料，不需要重試"""
    client, calls = _client([(200, {"stat": "很抱歉，沒有符合條件的資料！"})])
    async with client:
        df = await twse.fetch_institutional_flow_on(client, DAY)
    assert calls["n"] == 1
    assert df.empty
