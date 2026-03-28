import os
import tempfile
from pathlib import Path

import pytest
import yaml

from ibkr_datafetcher.config import (
    GatewayConfig,
    SyncConfig,
    DatabaseConfig,
    ScheduleConfig,
    Config,
    load_symbols_from_yaml,
)
from ibkr_datafetcher.types import SymbolConfig


class TestGatewayConfig:
    def test_defaults(self):
        config = GatewayConfig()
        assert config.host == "hgq-nas"
        assert config.port == 4004
        assert config.client_id == 1

    def test_custom_values(self):
        config = GatewayConfig(host="localhost", port=4005, client_id=2)
        assert config.host == "localhost"
        assert config.port == 4005
        assert config.client_id == 2


class TestSyncConfig:
    def test_defaults(self):
        config = SyncConfig()
        assert config.retry_attempts == 3
        assert config.retry_delay == 30

    def test_custom_values(self):
        config = SyncConfig(retry_attempts=5, retry_delay=60)
        assert config.retry_attempts == 5
        assert config.retry_delay == 60


class TestDatabaseConfig:
    def test_defaults(self):
        config = DatabaseConfig()
        assert config.path == "data/ibkr_cache.db"


class TestScheduleConfig:
    def test_defaults(self):
        config = ScheduleConfig()
        assert config.enabled is False
        assert config.cron == "0 9,16 * * *"


class TestConfig:
    def test_defaults(self):
        config = Config()
        assert config.gateway.host == "hgq-nas"
        assert config.sync.retry_attempts == 3
        assert config.database.path == "data/ibkr_cache.db"
        assert config.schedule.enabled is False

    def test_from_file_not_found(self):
        with pytest.raises(FileNotFoundError):
            Config.from_file("/nonexistent/path/config.yaml")

    def test_to_file_and_from_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.yaml"

            config = Config(
                gateway=GatewayConfig(host="test-host", port=5000, client_id=10),
                sync=SyncConfig(retry_attempts=5, retry_delay=120),
                database=DatabaseConfig(path="custom/path.db"),
                schedule=ScheduleConfig(enabled=True, cron="0 8 * * *"),
            )

            config.to_file(str(config_path))
            assert config_path.exists()

            loaded = Config.from_file(str(config_path))
            assert loaded.gateway.host == "test-host"
            assert loaded.gateway.port == 5000
            assert loaded.gateway.client_id == 10
            assert loaded.sync.retry_attempts == 5
            assert loaded.sync.retry_delay == 120
            assert loaded.database.path == "custom/path.db"
            assert loaded.schedule.enabled is True
            assert loaded.schedule.cron == "0 8 * * *"

    def test_to_file_creates_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "subdir" / "config.yaml"
            config = Config()
            config.to_file(str(config_path))
            assert config_path.exists()

    def test_partial_config_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.yaml"

            data = {
                "gateway": {"host": "custom-host"},
                "sync": {"retry_attempts": 10},
            }
            with open(config_path, "w") as f:
                yaml.dump(data, f)

            config = Config.from_file(str(config_path))
            assert config.gateway.host == "custom-host"
            assert config.gateway.port == 4004
            assert config.sync.retry_attempts == 10
            assert config.database.path == "data/ibkr_cache.db"


class TestLoadSymbolsFromYaml:
    def test_file_not_found(self):
        with pytest.raises(FileNotFoundError):
            load_symbols_from_yaml("/nonexistent/path/symbols.yaml")

    def test_load_symbols(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            symbols_path = Path(tmpdir) / "symbols.yaml"

            data = {
                "symbols": [
                    {
                        "symbol": "AAPL",
                        "name": "Apple Inc.",
                        "sec_type": "STK",
                        "exchange": "SMART",
                        "currency": "USD",
                    },
                    {
                        "symbol": "EURUSD",
                        "name": "Euro/USD",
                        "sec_type": "CASH",
                        "exchange": "IDEALPRO",
                        "currency": "USD",
                    },
                    {
                        "symbol": "VIX",
                        "name": "CBOE Volatility Index",
                        "sec_type": "IND",
                        "exchange": "CBOE",
                        "currency": "USD",
                        "what_to_show": "MIDPOINT",
                    },
                ]
            }
            with open(symbols_path, "w") as f:
                yaml.dump(data, f)

            symbols = load_symbols_from_yaml(str(symbols_path))

            assert len(symbols) == 3
            assert symbols[0].symbol == "AAPL"
            assert symbols[0].name == "Apple Inc."
            assert symbols[0].sec_type == "STK"
            assert symbols[1].symbol == "EURUSD"
            assert symbols[1].sec_type == "CASH"
            assert symbols[2].symbol == "VIX"
            assert symbols[2].what_to_show == "MIDPOINT"

    def test_empty_symbols_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            symbols_path = Path(tmpdir) / "symbols.yaml"

            data = {"symbols": []}
            with open(symbols_path, "w") as f:
                yaml.dump(data, f)

            symbols = load_symbols_from_yaml(str(symbols_path))
            assert len(symbols) == 0

    def test_symbols_with_defaults(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            symbols_path = Path(tmpdir) / "symbols.yaml"

            data = {
                "symbols": [
                    {
                        "symbol": "TSLA",
                        "name": "Tesla Inc.",
                    },
                ]
            }
            with open(symbols_path, "w") as f:
                yaml.dump(data, f)

            symbols = load_symbols_from_yaml(str(symbols_path))

            assert len(symbols) == 1
            assert symbols[0].symbol == "TSLA"
            assert symbols[0].sec_type == "STK"
            assert symbols[0].exchange == "SMART"
            assert symbols[0].currency == "USD"
            assert symbols[0].what_to_show == "TRADES"
