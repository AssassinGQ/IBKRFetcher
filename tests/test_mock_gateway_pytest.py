"""Pytest-based tests for mock IBKR gateway (UC-P0-1 through UC-P0-11)."""

import asyncio
from datetime import datetime, timedelta

import pytest
import pytest_asyncio
import ib_insync


@pytest_asyncio.fixture
async def ib(mock_gateway_port):
    """Connect an IB client to the mock gateway and disconnect after test."""
    client = ib_insync.IB()
    client.RequestTimeout = 10
    await client.connectAsync(
        host="127.0.0.1", port=mock_gateway_port,
        clientId=1, readonly=True, timeout=10,
    )
    yield client
    client.disconnect()


@pytest.mark.asyncio
async def test_connect_and_managed_accounts(ib):
    """UC-P0-1, UC-P0-11: connectAsync succeeds and returns managed accounts."""
    assert ib.isConnected()
    assert ib.managedAccounts() == ["DU0000001"]


@pytest.mark.asyncio
async def test_qualify_stk_contract(ib):
    """UC-P0-6: qualifyContractsAsync for STK (AAPL)."""
    contract = ib_insync.Stock("AAPL", "SMART", "USD")
    qualified = await ib.qualifyContractsAsync(contract)
    assert len(qualified) == 1
    assert qualified[0].conId == 265598


@pytest.mark.asyncio
async def test_qualify_ind_contract(ib):
    """UC-P0-6: qualifyContractsAsync for IND (VIX)."""
    contract = ib_insync.Index("VIX", "CBOE", "USD")
    qualified = await ib.qualifyContractsAsync(contract)
    assert len(qualified) == 1
    assert qualified[0].conId == 13455763


@pytest.mark.asyncio
async def test_qualify_unknown_contract(ib):
    """UC-P0-6: qualifyContractsAsync for unknown symbol returns empty."""
    contract = ib_insync.Stock("ZZZZZ", "SMART", "USD")
    qualified = await ib.qualifyContractsAsync(contract)
    assert not qualified or qualified[0].conId == 0


@pytest.mark.asyncio
async def test_historical_data_daily(ib):
    """UC-P0-4: reqHistoricalDataAsync returns correct daily bars."""
    contract = ib_insync.Stock("AAPL", "SMART", "USD")
    await ib.qualifyContractsAsync(contract)
    bars = await ib.reqHistoricalDataAsync(
        contract, endDateTime="", durationStr="10 D",
        barSizeSetting="1 day", whatToShow="TRADES",
        useRTH=True, formatDate=2, keepUpToDate=False,
    )
    assert len(bars) == 10
    for b in bars:
        assert b.open > 0
        assert b.high >= b.low
        assert b.volume >= 0


@pytest.mark.asyncio
async def test_historical_data_vix_midpoint(ib):
    """UC-P0-5: reqHistoricalDataAsync with whatToShow=MIDPOINT for VIX."""
    contract = ib_insync.Index("VIX", "CBOE", "USD")
    await ib.qualifyContractsAsync(contract)
    bars = await ib.reqHistoricalDataAsync(
        contract, endDateTime="", durationStr="1 W",
        barSizeSetting="1 hour", whatToShow="MIDPOINT",
        useRTH=True, formatDate=2, keepUpToDate=False,
    )
    assert len(bars) > 0
    assert all(b.close > 0 for b in bars)


@pytest.mark.asyncio
async def test_news_providers(ib):
    """UC-P0-7: reqNewsProvidersAsync returns providers."""
    providers = await ib.reqNewsProvidersAsync()
    assert len(providers) >= 3
    codes = [p.code for p in providers]
    assert "BRFG" in codes


@pytest.mark.asyncio
async def test_historical_news(ib):
    """UC-P0-7: reqHistoricalNewsAsync returns news items."""
    contract = ib_insync.Stock("AAPL", "SMART", "USD")
    await ib.qualifyContractsAsync(contract)
    end_time = datetime.now()
    start_time = end_time - timedelta(days=7)
    news = await ib.reqHistoricalNewsAsync(
        conId=contract.conId, providerCodes="BRFG",
        startDateTime=start_time.strftime("%Y%m%d-%H:%M:%S"),
        endDateTime=end_time.strftime("%Y%m%d-%H:%M:%S"),
        totalResults=5,
    )
    assert news
    assert hasattr(news[0], "articleId")
    assert hasattr(news[0], "headline")


@pytest.mark.asyncio
async def test_ticker_snapshot(ib):
    """UC-P0-8: reqTickersAsync returns bid/ask/last."""
    contract = ib_insync.Index("VIX", "CBOE", "USD")
    await ib.qualifyContractsAsync(contract)
    tickers = await ib.reqTickersAsync(contract)
    assert len(tickers) == 1
    t = tickers[0]
    assert t.bid > 0
    assert t.ask > 0
    assert t.last > 0


@pytest.mark.asyncio
async def test_smart_components(ib):
    """UC-P0-10: reqSmartComponentsAsync returns exchange components."""
    components = await ib.reqSmartComponentsAsync("BOBO")
    assert len(components) == 3


@pytest.mark.asyncio
async def test_deterministic_data(ib):
    """UC-P0-3: same request returns identical data (deterministic)."""
    contract = ib_insync.Stock("SPY", "SMART", "USD")
    await ib.qualifyContractsAsync(contract)
    end = datetime.now().strftime("%Y%m%d %H:%M:%S")
    bars1 = await ib.reqHistoricalDataAsync(
        contract, endDateTime=end, durationStr="5 D",
        barSizeSetting="1 day", whatToShow="TRADES",
        useRTH=True, formatDate=2, keepUpToDate=False,
    )
    bars2 = await ib.reqHistoricalDataAsync(
        contract, endDateTime=end, durationStr="5 D",
        barSizeSetting="1 day", whatToShow="TRADES",
        useRTH=True, formatDate=2, keepUpToDate=False,
    )
    assert len(bars1) == len(bars2)
    for b1, b2 in zip(bars1, bars2):
        assert b1.open == b2.open
        assert b1.close == b2.close
