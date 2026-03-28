import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

from ibkr_datafetcher.types import SymbolConfig, Timeframe
from ibkr_datafetcher.timeframe_prober import TimeRange, KlineProber, NewsProber


class TestTimeRange:
    def test_time_range_creation(self):
        start = datetime(2024, 1, 1, tzinfo=timezone.utc)
        end = datetime(2024, 1, 2, tzinfo=timezone.utc)
        tr = TimeRange(start, end)
        assert tr.start == start
        assert tr.end == end

    def test_time_range_repr(self):
        start = datetime(2024, 1, 1, tzinfo=timezone.utc)
        end = datetime(2024, 1, 2, tzinfo=timezone.utc)
        tr = TimeRange(start, end)
        assert "2024-01-01" in repr(tr)
        assert "2024-01-02" in repr(tr)


class TestKlineProber:
    def test_init(self):
        mock_client = MagicMock()
        mock_rate_limiter = MagicMock()
        mock_db = MagicMock()
        prober = KlineProber(mock_client, mock_rate_limiter, mock_db)
        assert prober._client == mock_client
        assert prober._rate_limiter == mock_rate_limiter
        assert prober._db == mock_db

    def test_get_pending_ranges_no_data_no_cache(self):
        mock_client = MagicMock()
        mock_rate_limiter = MagicMock()
        mock_db = MagicMock()
        mock_db.get_latest_bar_time.return_value = None
        mock_db.get_earliest_bar_time.return_value = None
        mock_client.make_contract.return_value = MagicMock()
        mock_client.get_historical_bars.return_value = []

        prober = KlineProber(mock_client, mock_rate_limiter, mock_db)
        config = SymbolConfig(symbol="AAPL", name="Apple", sec_type="STK",
                             exchange="SMART", currency="USD")
        ranges = prober.get_pending_ranges(config, Timeframe.D1)

        assert len(ranges) == 1
        assert ranges[0].start < ranges[0].end

    def test_get_pending_ranges_with_latest_bar(self):
        mock_client = MagicMock()
        mock_rate_limiter = MagicMock()
        mock_db = MagicMock()
        latest_ts = int((datetime.now(timezone.utc) - timedelta(hours=48)).timestamp())
        mock_db.get_latest_bar_time.return_value = latest_ts

        prober = KlineProber(mock_client, mock_rate_limiter, mock_db)
        config = SymbolConfig(symbol="AAPL", name="Apple", sec_type="STK",
                             exchange="SMART", currency="USD")
        ranges = prober.get_pending_ranges(config, Timeframe.D1)

        assert len(ranges) == 1
        latest_dt = datetime.fromtimestamp(latest_ts, tz=timezone.utc)
        assert ranges[0].start >= latest_dt

    def test_get_pending_ranges_already_synced(self):
        mock_client = MagicMock()
        mock_rate_limiter = MagicMock()
        mock_db = MagicMock()
        now = datetime.now(timezone.utc)
        latest_ts = int(now.timestamp())
        mock_db.get_latest_bar_time.return_value = latest_ts

        prober = KlineProber(mock_client, mock_rate_limiter, mock_db)
        config = SymbolConfig(symbol="AAPL", name="Apple", sec_type="STK",
                             exchange="SMART", currency="USD")
        ranges = prober.get_pending_ranges(config, Timeframe.D1)

        assert len(ranges) == 0

    def test_probe_earliest_time_with_cache(self):
        mock_client = MagicMock()
        mock_rate_limiter = MagicMock()
        mock_db = MagicMock()
        cached_ts = int(datetime(2020, 1, 1, tzinfo=timezone.utc).timestamp())
        mock_db.get_earliest_bar_time.return_value = cached_ts

        prober = KlineProber(mock_client, mock_rate_limiter, mock_db)
        config = SymbolConfig(symbol="AAPL", name="Apple", sec_type="STK",
                             exchange="SMART", currency="USD")
        result = prober._probe_earliest_time(config, Timeframe.D1)

        mock_client.make_contract.assert_not_called()
        assert result is not None

    def test_probe_earliest_time_api_error(self):
        mock_client = MagicMock()
        mock_rate_limiter = MagicMock()
        mock_db = MagicMock()
        mock_db.get_earliest_bar_time.return_value = None
        mock_client.make_contract.side_effect = Exception("API Error")

        prober = KlineProber(mock_client, mock_rate_limiter, mock_db)
        config = SymbolConfig(symbol="AAPL", name="Apple", sec_type="STK",
                             exchange="SMART", currency="USD")
        result = prober._probe_earliest_time(config, Timeframe.D1)

        assert result is None


class TestNewsProber:
    def test_init(self):
        mock_client = MagicMock()
        mock_rate_limiter = MagicMock()
        mock_db = MagicMock()
        prober = NewsProber(mock_client, mock_rate_limiter, mock_db)
        assert prober._client == mock_client
        assert prober._rate_limiter == mock_rate_limiter
        assert prober._db == mock_db

    def test_get_pending_ranges_no_news(self):
        mock_db = MagicMock()
        mock_db.get_latest_news_time.return_value = None

        prober = NewsProber(MagicMock(), MagicMock(), mock_db)
        config = SymbolConfig(symbol="AAPL", name="Apple", sec_type="STK",
                             exchange="SMART", currency="USD")
        ranges = prober.get_pending_ranges(config, days=30)

        assert len(ranges) == 1
        now = datetime.now(timezone.utc)
        assert (now - ranges[0].end).total_seconds() < 5

    def test_get_pending_ranges_with_news(self):
        mock_db = MagicMock()
        latest_ts = int((datetime.now(timezone.utc) - timedelta(hours=12)).timestamp())
        mock_db.get_latest_news_time.return_value = latest_ts

        prober = NewsProber(MagicMock(), MagicMock(), mock_db)
        config = SymbolConfig(symbol="AAPL", name="Apple", sec_type="STK",
                             exchange="SMART", currency="USD")
        ranges = prober.get_pending_ranges(config, days=30)

        assert len(ranges) == 1
        latest_dt = datetime.fromtimestamp(latest_ts, tz=timezone.utc)
        assert ranges[0].start >= latest_dt

    def test_get_pending_ranges_up_to_date(self):
        mock_db = MagicMock()
        future_ts = int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp())
        mock_db.get_latest_news_time.return_value = future_ts

        prober = NewsProber(MagicMock(), MagicMock(), mock_db)
        config = SymbolConfig(symbol="AAPL", name="Apple", sec_type="STK",
                             exchange="SMART", currency="USD")
        ranges = prober.get_pending_ranges(config, days=30)

        assert len(ranges) == 0
