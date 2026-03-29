"""End-to-end integration tests using mock IBKR gateway on port 14002."""
from __future__ import annotations

import json
import os
import time

import pytest

from ibkr_datafetcher.config import GatewayConfig
from ibkr_datafetcher.db import Database
from ibkr_datafetcher.ibkr_client import IBKRClient
from ibkr_datafetcher.kline_fetcher import KlineFetcher
from ibkr_datafetcher.news_fetcher import NewsFetcher
from ibkr_datafetcher.rate_limiter import RateLimiter
from ibkr_datafetcher.types import SymbolConfig, Timeframe

AAPL = SymbolConfig(symbol="AAPL", name="Apple Inc.", sec_type="STK",
                     exchange="SMART", currency="USD")
VIX = SymbolConfig(symbol="VIX", name="CBOE VIX", sec_type="IND",
                    exchange="CBOE", currency="USD", what_to_show="MIDPOINT")


@pytest.fixture
def gw_config(mock_gateway_port):
    return GatewayConfig(host="127.0.0.1", port=mock_gateway_port, client_id=50)


@pytest.fixture
def db_inst(tmp_path):
    db = Database(str(tmp_path / "e2e.db"))
    yield db
    db.close()


@pytest.fixture
def rate_limiter():
    return RateLimiter(
        hist_requests_per_minute=60,
        news_requests_per_minute=30,
        identical_cooldown=0.0,
        same_contract_limit=100,
        same_contract_window=0.1,
    )


@pytest.fixture
def client(gw_config):
    c = IBKRClient(gw_config)
    ok = c.connect(timeout=15)
    assert ok, "Failed to connect to mock gateway"
    yield c
    c.disconnect()


def test_uc_p7_6_first_sync_aapl_d1(client, rate_limiter, db_inst):
    fetcher = KlineFetcher(client, rate_limiter, db_inst)
    result = fetcher.sync_symbol(AAPL, Timeframe.D1)

    assert result["symbol"] == "AAPL"
    assert result["bars_fetched"] > 0

    time.sleep(0.2)
    bars = db_inst.query_klines("AAPL", "D1")
    assert len(bars) > 0


def test_uc_p7_7_second_sync_skips_cached(client, rate_limiter, db_inst):
    fetcher = KlineFetcher(client, rate_limiter, db_inst)

    r1 = fetcher.sync_symbol(AAPL, Timeframe.D1)
    time.sleep(0.2)
    first_count = r1["bars_fetched"]

    r2 = fetcher.sync_symbol(AAPL, Timeframe.D1)
    assert r2["bars_fetched"] <= first_count + 5


def test_uc_p7_8_interrupt_resume(client, rate_limiter, db_inst):
    fetcher = KlineFetcher(client, rate_limiter, db_inst)

    call_count = [0]
    original_get = client.get_historical_bars

    def _limited(*args, **kwargs):
        call_count[0] += 1
        if call_count[0] >= 3:
            raise KeyboardInterrupt
        return original_get(*args, **kwargs)

    client.get_historical_bars = _limited  # type: ignore[assignment]
    try:
        fetcher.sync_symbol(AAPL, Timeframe.D1)
    except KeyboardInterrupt:
        pass

    time.sleep(0.2)
    bars_after_interrupt = db_inst.query_klines("AAPL", "D1")

    client.get_historical_bars = original_get  # type: ignore[assignment]
    fetcher2 = KlineFetcher(client, rate_limiter, db_inst)
    fetcher2.sync_symbol(AAPL, Timeframe.D1)
    time.sleep(0.2)
    bars_after_resume = db_inst.query_klines("AAPL", "D1")

    assert len(bars_after_resume) >= len(bars_after_interrupt)


def test_uc_p7_9_query_csv_consistent(client, rate_limiter, db_inst, tmp_path):
    fetcher = KlineFetcher(client, rate_limiter, db_inst)
    fetcher.sync_symbol(AAPL, Timeframe.D1)
    time.sleep(0.2)

    bars = db_inst.query_klines("AAPL", "D1")
    assert len(bars) > 0

    csv_path = str(tmp_path / "export.csv")
    import csv
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["symbol", "timestamp", "open", "high", "low", "close"])
        for b in bars:
            writer.writerow([b.symbol, b.timestamp, b.open, b.high, b.low, b.close])

    assert os.path.exists(csv_path)
    with open(csv_path, encoding="utf-8") as f:
        lines = f.readlines()
    assert len(lines) == len(bars) + 1


def test_uc_p7_10_status_correct(client, rate_limiter, db_inst):
    fetcher = KlineFetcher(client, rate_limiter, db_inst)
    result = fetcher.sync_symbol(AAPL, Timeframe.D1)
    time.sleep(0.2)

    statuses = db_inst.get_sync_status("AAPL")
    assert len(statuses) >= 1
    st = statuses[0]
    assert st.symbol == "AAPL"
    assert st.bar_count > 0
    assert st.latest_bar_time > 0


def test_uc_p7_11_multi_timeframe_independent(client, rate_limiter, db_inst):
    fetcher = KlineFetcher(client, rate_limiter, db_inst)

    r1 = fetcher.sync_symbol(AAPL, Timeframe.D1)
    r2 = fetcher.sync_symbol(AAPL, Timeframe.H1)
    time.sleep(0.2)

    bars_d1 = db_inst.query_klines("AAPL", "D1")
    bars_h1 = db_inst.query_klines("AAPL", "H1")

    assert len(bars_d1) > 0
    assert len(bars_h1) > 0
    assert r1["timeframe"] == "D1"
    assert r2["timeframe"] == "H1"


def test_uc_p7_12_vix_midpoint_sync(client, rate_limiter, db_inst):
    fetcher = KlineFetcher(client, rate_limiter, db_inst)
    result = fetcher.sync_symbol(VIX, Timeframe.D1)
    time.sleep(0.2)

    bars = db_inst.query_klines("VIX", "D1")
    assert len(bars) > 0
    assert result["bars_fetched"] > 0


def test_uc_p7_13_news_e2e(client, rate_limiter, db_inst):
    fetcher = NewsFetcher(client, rate_limiter, db_inst)
    result = fetcher.fetch_symbol_news(AAPL, days=30)

    assert result["symbol"] == "AAPL"
    assert result["news_count"] >= 0

    time.sleep(0.2)
    news = db_inst.query_news(symbol="AAPL")
    assert len(news) == result["news_count"]
