import os
import tempfile
import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone

from ibkr_datafetcher.config import Config, load_config, GatewayConfig, SyncConfig, DatabaseConfig
from ibkr_datafetcher.db import Database
from ibkr_datafetcher.kline_fetcher import KlineFetcher
from ibkr_datafetcher.news_fetcher import NewsFetcher
from ibkr_datafetcher.rate_limiter import RateLimiter, RateLimitConfig
from ibkr_datafetcher.scheduler import Scheduler
from ibkr_datafetcher.timeframe_prober import KlineProber, NewsProber
from ibkr_datafetcher.types import SymbolConfig, KlineBar, SyncStatus, Timeframe


class TestIntegrationWorkflow:
    def test_load_config_with_symbols(self, tmp_path):
        config_data = {
            "gateway": {"host": "test-host", "port": 4004, "client_id": 2},
            "sync": {"retry_attempts": 5, "retry_delay": 60},
            "database": {"path": "test.db"},
            "schedule": {"enabled": True, "cron": "0 8 * * *"},
        }
        symbols_data = {
            "symbols": [
                {
                    "symbol": "AAPL",
                    "name": "Apple",
                    "sec_type": "STK",
                    "exchange": "SMART",
                    "currency": "USD",
                }
            ]
        }

        import yaml
        config_file = tmp_path / "config.yaml"
        symbols_file = tmp_path / "symbols.yaml"
        config_file.write_text(yaml.dump(config_data))
        symbols_file.write_text(yaml.dump(symbols_data))

        with tempfile.TemporaryDirectory() as tmpdir:
            old_cwd = os.getcwd()
            os.chdir(tmpdir)
            try:
                os.makedirs("configs", exist_ok=True)
                import shutil
                shutil.copy(config_file, "configs/config.yaml")
                shutil.copy(symbols_file, "configs/symbols.yaml")

                cfg = load_config("configs/config.yaml")

                assert cfg.gateway.host == "test-host"
                assert cfg.gateway.port == 4004
                assert cfg.gateway.client_id == 2
                assert cfg.sync.retry_attempts == 5
                assert cfg.sync.retry_delay == 60
                assert cfg.database.path == "test.db"
                assert cfg.schedule.enabled is True
                assert len(cfg.sync.symbols) == 1
                assert cfg.sync.symbols[0].symbol == "AAPL"
            finally:
                os.chdir(old_cwd)

    def test_database_write_and_read_klines(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        db = Database(db_path)
        db.start()

        bar_time = datetime(2023, 1, 1, tzinfo=timezone.utc)
        bar = KlineBar(
            symbol="AAPL",
            timeframe="D1",
            timestamp=1700000000,
            open=150.0,
            high=151.0,
            low=149.0,
            close=150.5,
            volume=1000000.0,
            bar_count=100,
            bar_time=bar_time,
        )
        db.write_kline(bar)
        db.stop()

        db2 = Database(db_path)
        db2.start()
        try:
            result = db2.get_bars("AAPL", "D1", 0, 9999999999)
            assert len(result) == 1
            assert result[0].symbol == "AAPL"
            assert result[0].close == 150.5
        finally:
            db2.stop()

    def test_database_sync_status_update(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        db = Database(db_path)
        db.start()

        status = SyncStatus(
            symbol="AAPL",
            timeframe="D1",
            latest_bar_time=1700000000,
            bar_count=100,
            synced_at=datetime.now(timezone.utc),
        )
        db.update_sync_status(status)
        db.stop()

    def test_kline_prober_init(self):
        mock_client = MagicMock()
        mock_rate_limiter = MagicMock()
        mock_db = MagicMock()
        prober = KlineProber(mock_client, mock_rate_limiter, mock_db)
        assert prober._client == mock_client
        assert prober._rate_limiter == mock_rate_limiter
        assert prober._db == mock_db

    def test_news_prober_init(self):
        mock_client = MagicMock()
        mock_rate_limiter = MagicMock()
        mock_db = MagicMock()
        prober = NewsProber(mock_client, mock_rate_limiter, mock_db)
        assert prober._client == mock_client
        assert prober._rate_limiter == mock_rate_limiter
        assert prober._db == mock_db

    def test_kline_fetcher_integration(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        db = Database(db_path)
        db.start()

        try:
            mock_client = MagicMock()
            mock_contract = MagicMock()
            mock_client.make_contract.return_value = mock_contract
            mock_client.get_historical_bars.return_value = []

            rate_limiter = RateLimiter(RateLimitConfig())
            fetcher = KlineFetcher(mock_client, rate_limiter, db)

            symbol_config = SymbolConfig(
                symbol="AAPL",
                name="Apple",
                sec_type="STK",
                exchange="SMART",
                currency="USD",
            )

            result = fetcher.sync_symbol(symbol_config, Timeframe.D1)
            assert "bars_fetched" in result
            assert "errors" in result
            assert "ranges_processed" in result
        finally:
            db.stop()

    def test_kline_fetcher_sync_all(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        db = Database(db_path)
        db.start()

        try:
            mock_client = MagicMock()
            mock_client.make_contract.return_value = MagicMock()
            mock_client.get_historical_bars.return_value = []

            rate_limiter = RateLimiter(RateLimitConfig())
            fetcher = KlineFetcher(mock_client, rate_limiter, db)

            symbols = [
                SymbolConfig(
                    symbol="AAPL",
                    name="Apple",
                    sec_type="STK",
                    exchange="SMART",
                    currency="USD",
                )
            ]

            result = fetcher.sync_all(symbols, [Timeframe.D1])
            assert "total_bars" in result
            assert "symbols_processed" in result
            assert "errors" in result
        finally:
            db.stop()

    def test_news_fetcher_integration(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        db = Database(db_path)
        db.start()

        try:
            mock_client = MagicMock()
            mock_client.get_historical_news.return_value = []

            rate_limiter = RateLimiter(RateLimitConfig())
            fetcher = NewsFetcher(mock_client, rate_limiter, db)

            symbol_config = SymbolConfig(
                symbol="AAPL",
                name="Apple",
                sec_type="STK",
                exchange="SMART",
                currency="USD",
            )

            result = fetcher.fetch_symbol_news(symbol_config, days=30)
            assert "news_count" in result
            assert "errors" in result
        finally:
            db.stop()

    def test_scheduler_init(self):
        mock_fetcher = MagicMock()
        symbols = [
            SymbolConfig(
                symbol="AAPL",
                name="Apple",
                sec_type="STK",
                exchange="SMART",
                currency="USD",
            )
        ]
        scheduler = Scheduler(mock_fetcher, symbols, [Timeframe.D1])

        assert scheduler._fetcher == mock_fetcher
        assert scheduler._symbols == symbols
        assert scheduler._timeframes == [Timeframe.D1]


class TestConfigDefaultValues:
    def test_config_defaults(self):
        cfg = Config()
        assert cfg.gateway.host == "hgq-nas"
        assert cfg.gateway.port == 4004
        assert cfg.gateway.client_id == 1
        assert cfg.sync.retry_attempts == 3
        assert cfg.sync.retry_delay == 30
        assert cfg.database.path == "data/ibkr_cache.db"
        assert cfg.schedule.enabled is False
        assert cfg.schedule.cron == "0 9,16 * * *"


class TestSymbolConfigCreation:
    def test_stock_symbol_config(self):
        cfg = SymbolConfig(
            symbol="AAPL",
            name="Apple Inc.",
            sec_type="STK",
            exchange="SMART",
            currency="USD",
        )
        assert cfg.symbol == "AAPL"
        assert cfg.sec_type == "STK"

    def test_forex_symbol_config(self):
        cfg = SymbolConfig(
            symbol="EURUSD",
            name="Euro/USD",
            sec_type="CASH",
            exchange="IDEALPRO",
            currency="USD",
        )
        assert cfg.symbol == "EURUSD"
        assert cfg.sec_type == "CASH"
        assert cfg.exchange == "IDEALPRO"
