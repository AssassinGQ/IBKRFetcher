import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from ibkr_datafetcher.config import SymbolConfig
from ibkr_datafetcher.news_fetcher import NewsFetcher
from ibkr_datafetcher.types import NewsItem


class TestNewsFetcher:
    def test_init(self):
        mock_client = MagicMock()
        mock_rate_limiter = MagicMock()
        mock_db = MagicMock()
        fetcher = NewsFetcher(mock_client, mock_rate_limiter, mock_db)
        assert fetcher._client == mock_client
        assert fetcher._rate_limiter == mock_rate_limiter
        assert fetcher._db == mock_db

    def test_fetch_symbol_news_contract_error(self):
        mock_client = MagicMock()
        mock_rate_limiter = MagicMock()
        mock_db = MagicMock()
        mock_client.make_contract.side_effect = Exception("Contract Error")

        fetcher = NewsFetcher(mock_client, mock_rate_limiter, mock_db)
        config = SymbolConfig(symbol="AAPL", name="Apple", sec_type="STK",
                             exchange="SMART", currency="USD")
        result = fetcher.fetch_symbol_news(config)

        assert result["symbol"] == "AAPL"
        assert result["news_count"] == 0
        assert "Contract Error" in result["errors"]

    def test_fetch_symbol_news_qualify_failed(self):
        mock_client = MagicMock()
        mock_rate_limiter = MagicMock()
        mock_db = MagicMock()
        mock_client.make_contract.return_value = MagicMock()
        mock_client.qualify_contract.return_value = 0

        fetcher = NewsFetcher(mock_client, mock_rate_limiter, mock_db)
        config = SymbolConfig(symbol="AAPL", name="Apple", sec_type="STK",
                             exchange="SMART", currency="USD")
        result = fetcher.fetch_symbol_news(config)

        assert result["news_count"] == 0
        assert "Contract not qualified" in result["errors"]

    def test_fetch_symbol_news_success(self):
        mock_client = MagicMock()
        mock_rate_limiter = MagicMock()
        mock_db = MagicMock()
        mock_client.make_contract.return_value = MagicMock()
        mock_client.qualify_contract.return_value = 12345

        now = datetime.now(timezone.utc)
        news_list = [
            NewsItem(article_id="news1", symbol="AAPL", headline="AAPL Reports Q1",
                    provider_code="BRFG", timestamp=int(now.timestamp())),
            NewsItem(article_id="news2", symbol="AAPL", headline="AAPL Stock Up",
                    provider_code="BRFUPDN", timestamp=int(now.timestamp())),
        ]
        mock_client.get_historical_news.return_value = news_list

        fetcher = NewsFetcher(mock_client, mock_rate_limiter, mock_db)
        config = SymbolConfig(symbol="AAPL", name="Apple", sec_type="STK",
                             exchange="SMART", currency="USD")
        result = fetcher.fetch_symbol_news(config)

        assert result["news_count"] == 2
        assert mock_db.write_news.call_count == 2

    def test_fetch_symbol_news_api_error(self):
        mock_client = MagicMock()
        mock_rate_limiter = MagicMock()
        mock_db = MagicMock()
        mock_client.make_contract.return_value = MagicMock()
        mock_client.qualify_contract.return_value = 12345
        mock_client.get_historical_news.side_effect = Exception("API Error")

        fetcher = NewsFetcher(mock_client, mock_rate_limiter, mock_db)
        config = SymbolConfig(symbol="AAPL", name="Apple", sec_type="STK",
                             exchange="SMART", currency="USD")
        result = fetcher.fetch_symbol_news(config)

        assert result["news_count"] == 0
        assert "API Error" in result["errors"]

    def test_fetch_symbol_news_empty_result(self):
        mock_client = MagicMock()
        mock_rate_limiter = MagicMock()
        mock_db = MagicMock()
        mock_client.make_contract.return_value = MagicMock()
        mock_client.qualify_contract.return_value = 12345
        mock_client.get_historical_news.return_value = []

        fetcher = NewsFetcher(mock_client, mock_rate_limiter, mock_db)
        config = SymbolConfig(symbol="AAPL", name="Apple", sec_type="STK",
                             exchange="SMART", currency="USD")
        result = fetcher.fetch_symbol_news(config)

        assert result["news_count"] == 0
        assert mock_db.write_news.call_count == 0
