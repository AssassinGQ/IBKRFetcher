from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from unittest import mock

import pytest

from ibkr_datafetcher.db import Database
from ibkr_datafetcher.news_fetcher import NewsFetcher
from ibkr_datafetcher.types import NewsItem, SymbolConfig

AAPL = SymbolConfig(symbol="AAPL", name="Apple", sec_type="STK",
                     exchange="SMART", currency="USD")


@pytest.fixture
def db_inst(tmp_path):
    db = Database(str(tmp_path / "test.db"))
    yield db
    db.close()


@pytest.fixture
def mock_client():
    c = mock.MagicMock()
    c.make_contract.return_value = mock.MagicMock()
    c.qualify_contract.return_value = 265598
    return c


@pytest.fixture
def mock_rl():
    return mock.MagicMock()


def test_uc_p5_26_full_news_chain(db_inst, mock_client, mock_rl):
    now = datetime.now(tz=timezone.utc)
    items = [
        NewsItem(article_id="art1", symbol=None, headline="H1",
                 provider_code="BRFG", timestamp=int(now.timestamp())),
        NewsItem(article_id="art2", symbol=None, headline="H2",
                 provider_code="DJNL", timestamp=int((now - timedelta(hours=1)).timestamp())),
    ]
    mock_client.get_historical_news.return_value = items

    fetcher = NewsFetcher(mock_client, mock_rl, db_inst)
    result = fetcher.fetch_symbol_news(AAPL, days=30)

    assert result["symbol"] == "AAPL"
    assert result["news_count"] == 2

    mock_client.make_contract.assert_called_once()
    mock_client.qualify_contract.assert_called_once()
    mock_rl.acquire.assert_called()
    for call in mock_rl.acquire.call_args_list:
        assert call.kwargs.get("request_type") == "news"

    time.sleep(0.1)
    stored = db_inst.query_news(symbol="AAPL")
    assert len(stored) == 2
    assert stored[0].symbol == "AAPL"


def test_uc_p5_27_news_result_shape(db_inst, mock_client, mock_rl):
    mock_client.get_historical_news.return_value = []

    fetcher = NewsFetcher(mock_client, mock_rl, db_inst)
    result = fetcher.fetch_symbol_news(AAPL, days=30)

    assert "symbol" in result
    assert "news_count" in result
    assert result["news_count"] == 0
