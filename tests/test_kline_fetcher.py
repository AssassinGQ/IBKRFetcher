import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

from ibkr_datafetcher.config import GatewayConfig, SymbolConfig
from ibkr_datafetcher.kline_fetcher import KlineFetcher
from ibkr_datafetcher.types import KlineBar, Timeframe


class TestKlineFetcher:
    def test_init(self):
        mock_client = MagicMock()
        mock_rate_limiter = MagicMock()
        mock_db = MagicMock()
        fetcher = KlineFetcher(mock_client, mock_rate_limiter, mock_db)
        assert fetcher._client == mock_client
        assert fetcher._rate_limiter == mock_rate_limiter
        assert fetcher._db == mock_db

    def test_sync_symbol_make_contract_error(self):
        mock_client = MagicMock()
        mock_client.make_contract.side_effect = Exception("Contract Error")
        mock_rate_limiter = MagicMock()
        mock_db = MagicMock()

        fetcher = KlineFetcher(mock_client, mock_rate_limiter, mock_db)
        config = SymbolConfig(symbol="AAPL", name="Apple", sec_type="STK",
                             exchange="SMART", currency="USD")
        result = fetcher.sync_symbol(config, Timeframe.D1)

        assert result["symbol"] == "AAPL"
        assert result["bars_fetched"] == 0
        assert "Contract Error" in result["errors"]

    def test_sync_symbol_no_pending_ranges(self):
        mock_client = MagicMock()
        mock_db = MagicMock()
        mock_rate_limiter = MagicMock()
        mock_contract = MagicMock()
        mock_client.make_contract.return_value = mock_contract
        mock_db.get_latest_bar_time.return_value = None
        mock_db.get_earliest_bar_time.return_value = None
        mock_client.get_historical_bars.return_value = []

        fetcher = KlineFetcher(mock_client, mock_rate_limiter, mock_db)
        config = SymbolConfig(symbol="AAPL", name="Apple", sec_type="STK",
                             exchange="SMART", currency="USD")

        with patch.object(fetcher._prober, 'get_pending_ranges', return_value=[]):
            result = fetcher.sync_symbol(config, Timeframe.D1)

        assert result["bars_fetched"] == 0
        assert result["ranges_processed"] == 0

    def test_sync_symbol_success(self):
        mock_client = MagicMock()
        mock_db = MagicMock()
        mock_rate_limiter = MagicMock()
        mock_contract = MagicMock()
        mock_client.make_contract.return_value = mock_contract

        now = datetime.now(timezone.utc)
        bars = [
            KlineBar(symbol="AAPL", timeframe="D1", timestamp=1000, open=150.0, high=151.0,
                   low=149.0, close=150.5, volume=1000000, bar_count=100, bar_time=now),
            KlineBar(symbol="AAPL", timeframe="D1", timestamp=2000, open=150.5, high=152.0,
                   low=150.0, close=151.5, volume=1100000, bar_count=110, bar_time=now),
        ]
        mock_client.get_historical_bars.return_value = bars

        prober_ranges = MagicMock()
        prober_ranges.__iter__ = lambda self: iter([MagicMock(start=now-timedelta(days=1), end=now)])

        fetcher = KlineFetcher(mock_client, mock_rate_limiter, mock_db)
        config = SymbolConfig(symbol="AAPL", name="Apple", sec_type="STK",
                             exchange="SMART", currency="USD")

        with patch.object(fetcher._prober, 'get_pending_ranges', return_value=[MagicMock(start=now-timedelta(days=1), end=now)]):
            result = fetcher.sync_symbol(config, Timeframe.D1)

        assert result["bars_fetched"] == 2
        assert result["ranges_processed"] == 1
        assert len(result["errors"]) == 0
        assert mock_db.write_kline.call_count == 2

    def test_sync_symbol_progress_callback(self):
        mock_client = MagicMock()
        mock_db = MagicMock()
        mock_rate_limiter = MagicMock()
        mock_client.make_contract.return_value = MagicMock()

        now = datetime.now(timezone.utc)
        bars = [
            KlineBar(symbol="AAPL", timeframe="D1", timestamp=1000, open=150.0, high=151.0,
                   low=149.0, close=150.5, volume=1000000, bar_count=100, bar_time=now),
        ]
        mock_client.get_historical_bars.return_value = bars

        callback_calls = []
        def progress_callback(progress):
            callback_calls.append(progress)

        from ibkr_datafetcher.timeframe_prober import TimeRange
        prober_ranges = [TimeRange(start=now-timedelta(days=1), end=now)]

        fetcher = KlineFetcher(mock_client, mock_rate_limiter, mock_db)
        fetcher._prober.get_pending_ranges = MagicMock(return_value=prober_ranges)
        config = SymbolConfig(symbol="AAPL", name="Apple", sec_type="STK",
                             exchange="SMART", currency="USD")

        result = fetcher.sync_symbol(config, Timeframe.D1, progress_callback)

        assert len(callback_calls) == 1

    def test_sync_all_empty_symbols(self):
        mock_client = MagicMock()
        mock_db = MagicMock()
        mock_rate_limiter = MagicMock()

        fetcher = KlineFetcher(mock_client, mock_rate_limiter, mock_db)
        result = fetcher.sync_all(symbols=[], timeframes=[Timeframe.D1])

        assert result["total_bars"] == 0
        assert result["symbols_processed"] == 0

    def test_sync_all_multiple_symbols(self):
        mock_client = MagicMock()
        mock_db = MagicMock()
        mock_rate_limiter = MagicMock()
        mock_client.make_contract.return_value = MagicMock()

        now = datetime.now(timezone.utc)
        bars = [KlineBar(symbol="AAPL", timeframe="D1", timestamp=1000, open=150.0,
                        high=151.0, low=149.0, close=150.5, volume=1000000,
                        bar_count=100, bar_time=now)]
        mock_client.get_historical_bars.return_value = bars

        fetcher = KlineFetcher(mock_client, mock_rate_limiter, mock_db)
        symbols = [
            SymbolConfig(symbol="AAPL", name="Apple", sec_type="STK", exchange="SMART", currency="USD"),
            SymbolConfig(symbol="MSFT", name="Microsoft", sec_type="STK", exchange="SMART", currency="USD"),
        ]

        with patch.object(fetcher._prober, 'get_pending_ranges', return_value=[MagicMock(start=now-timedelta(days=1), end=now)]):
            result = fetcher.sync_all(symbols=symbols, timeframes=[Timeframe.D1])

        assert result["symbols_processed"] == 2

    def test_duration_str_days(self):
        mock_client = MagicMock()
        mock_db = MagicMock()
        mock_rate_limiter = MagicMock()

        fetcher = KlineFetcher(mock_client, mock_rate_limiter, mock_db)
        assert fetcher._duration_str(timedelta(days=5)) == "5 D"

    def test_duration_str_hours(self):
        mock_client = MagicMock()
        mock_db = MagicMock()
        mock_rate_limiter = MagicMock()

        fetcher = KlineFetcher(mock_client, mock_rate_limiter, mock_db)
        assert fetcher._duration_str(timedelta(hours=4)) == "4 H"

    def test_duration_str_minutes(self):
        mock_client = MagicMock()
        mock_db = MagicMock()
        mock_rate_limiter = MagicMock()

        fetcher = KlineFetcher(mock_client, mock_rate_limiter, mock_db)
        assert fetcher._duration_str(timedelta(minutes=30)) == "30 M"
