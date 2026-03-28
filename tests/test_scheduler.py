import pytest
from unittest.mock import MagicMock, patch

from ibkr_datafetcher.config import SymbolConfig
from ibkr_datafetcher.scheduler import Scheduler
from ibkr_datafetcher.types import Timeframe


class TestScheduler:
    def test_init(self):
        mock_fetcher = MagicMock()
        symbols = [
            SymbolConfig(symbol="AAPL", name="Apple", sec_type="STK", exchange="SMART", currency="USD"),
        ]
        scheduler = Scheduler(mock_fetcher, symbols)

        assert scheduler._fetcher == mock_fetcher
        assert scheduler._symbols == symbols
        assert scheduler._timeframes is None

    def test_init_with_timeframes(self):
        mock_fetcher = MagicMock()
        symbols = []
        timeframes = [Timeframe.D1, Timeframe.H1]
        scheduler = Scheduler(mock_fetcher, symbols, timeframes)

        assert scheduler._timeframes == timeframes

    def test_start_invalid_cron(self):
        mock_fetcher = MagicMock()
        scheduler = Scheduler(mock_fetcher, [])

        with pytest.raises(ValueError, match="Invalid cron expression"):
            scheduler.start("invalid cron")

    @patch("apscheduler.schedulers.background.BackgroundScheduler")
    def test_start_valid_cron(self, mock_scheduler_class):
        mock_fetcher = MagicMock()
        mock_scheduler_instance = MagicMock()
        mock_scheduler_class.return_value = mock_scheduler_instance

        symbols = [SymbolConfig(symbol="AAPL", name="Apple", sec_type="STK", exchange="SMART", currency="USD")]
        scheduler = Scheduler(mock_fetcher, symbols)

        with patch.object(scheduler, '_running', True):
            pass

        scheduler._running = False

    @patch("apscheduler.schedulers.background.BackgroundScheduler")
    def test_stop(self, mock_scheduler_class):
        mock_scheduler_instance = MagicMock()
        mock_scheduler_class.return_value = mock_scheduler_instance

        mock_fetcher = MagicMock()
        scheduler = Scheduler(mock_fetcher, [])
        scheduler._scheduler = mock_scheduler_instance

        scheduler.stop()

        mock_scheduler_instance.shutdown.assert_called_once_with(wait=False)
        assert scheduler._running is False

    @patch("apscheduler.schedulers.background.BackgroundScheduler")
    def test_run_once(self, mock_scheduler_class):
        mock_fetcher = MagicMock()
        mock_fetcher.sync_all.return_value = {"total_bars": 100, "symbols_processed": 1, "errors": []}

        mock_scheduler_instance = MagicMock()
        mock_scheduler_class.return_value = mock_scheduler_instance

        symbols = [SymbolConfig(symbol="AAPL", name="Apple", sec_type="STK", exchange="SMART", currency="USD")]
        scheduler = Scheduler(mock_fetcher, symbols)

        result = scheduler.run_once()

        mock_fetcher.sync_all.assert_called_once_with(symbols, None)
        assert result["total_bars"] == 100
