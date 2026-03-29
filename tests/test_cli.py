from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from unittest import mock

import pytest
from click.testing import CliRunner

from ibkr_datafetcher.cli import main
from ibkr_datafetcher.db import Database
from ibkr_datafetcher.types import KlineBar, NewsItem, SyncStatus, Timeframe

CONFIGS_DIR = os.path.join(os.path.dirname(__file__), "..", "configs")
CONFIG_PATH = os.path.join(CONFIGS_DIR, "config.yaml")
SYMBOLS_PATH = os.path.join(CONFIGS_DIR, "symbols.yaml")


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def tmp_db(tmp_path):
    db_path = str(tmp_path / "test.db")
    db = Database(db_path)
    yield db, db_path
    db.close()


def test_uc_p6_1_help_lists_commands(runner):
    result = runner.invoke(main, ["--help"])
    assert result.exit_code == 0
    for cmd in ("sync", "query", "status", "news", "serve", "reconnect"):
        assert cmd in result.output


@mock.patch("ibkr_datafetcher.cli._load_config")
@mock.patch("ibkr_datafetcher.cli._load_symbols")
@mock.patch("ibkr_datafetcher.cli.IBKRClient")
@mock.patch("ibkr_datafetcher.cli.Database")
@mock.patch("ibkr_datafetcher.cli.KlineFetcher")
def test_uc_p6_2_sync_calls_sync_all(mock_fetcher_cls, mock_db_cls, mock_client_cls,
                                      mock_load_sym, mock_load_cfg, runner):
    from ibkr_datafetcher.config import GatewayConfig, SyncConfig, DatabaseConfig, ScheduleConfig, Config
    from ibkr_datafetcher.types import SymbolConfig

    cfg = Config(GatewayConfig("127.0.0.1", 4012, 1),
                 SyncConfig(3, 30), DatabaseConfig("test.db"), ScheduleConfig(False, ""))
    mock_load_cfg.return_value = cfg
    mock_load_sym.return_value = [
        SymbolConfig(symbol="AAPL", name="Apple"),
        SymbolConfig(symbol="MSFT", name="MSFT"),
    ]
    mock_client_inst = mock_client_cls.return_value
    mock_client_inst.connect.return_value = True

    mock_fetcher_inst = mock_fetcher_cls.return_value
    mock_fetcher_inst.sync_all.return_value = {
        "total_bars": 100, "symbols_processed": 1, "errors": [],
    }

    result = runner.invoke(main, ["sync", "--symbols", "AAPL"])
    assert result.exit_code == 0
    assert "100 bars fetched" in result.output
    mock_fetcher_inst.sync_all.assert_called_once()


@mock.patch("ibkr_datafetcher.cli._load_config")
@mock.patch("ibkr_datafetcher.cli._load_symbols")
@mock.patch("ibkr_datafetcher.cli.IBKRClient")
@mock.patch("ibkr_datafetcher.cli.Database")
@mock.patch("ibkr_datafetcher.cli.KlineFetcher")
def test_uc_p6_3_sync_with_timeframes(mock_fetcher_cls, mock_db_cls, mock_client_cls,
                                       mock_load_sym, mock_load_cfg, runner):
    from ibkr_datafetcher.config import GatewayConfig, SyncConfig, DatabaseConfig, ScheduleConfig, Config
    from ibkr_datafetcher.types import SymbolConfig

    cfg = Config(GatewayConfig("127.0.0.1", 4012, 1),
                 SyncConfig(3, 30), DatabaseConfig("test.db"), ScheduleConfig(False, ""))
    mock_load_cfg.return_value = cfg
    mock_load_sym.return_value = [
        SymbolConfig(symbol="AAPL", name="Apple"),
        SymbolConfig(symbol="MSFT", name="MSFT"),
    ]
    mock_client_inst = mock_client_cls.return_value
    mock_client_inst.connect.return_value = True

    mock_fetcher_inst = mock_fetcher_cls.return_value
    mock_fetcher_inst.sync_all.return_value = {
        "total_bars": 50, "symbols_processed": 2, "errors": [],
    }

    result = runner.invoke(main, ["sync", "--symbols", "AAPL,MSFT",
                                  "--timeframes", "1 day,1 hour"])
    assert result.exit_code == 0
    call_args = mock_fetcher_inst.sync_all.call_args
    tfs = call_args.kwargs.get("timeframes") or call_args[0][1] if len(call_args[0]) > 1 else call_args.kwargs.get("timeframes")
    assert tfs is not None


@mock.patch("ibkr_datafetcher.cli._load_config")
@mock.patch("ibkr_datafetcher.cli._load_symbols")
@mock.patch("ibkr_datafetcher.cli.IBKRClient")
@mock.patch("ibkr_datafetcher.cli.Database")
@mock.patch("ibkr_datafetcher.cli.KlineFetcher")
def test_uc_p6_4_sync_no_args_uses_all(mock_fetcher_cls, mock_db_cls, mock_client_cls,
                                        mock_load_sym, mock_load_cfg, runner):
    from ibkr_datafetcher.config import GatewayConfig, SyncConfig, DatabaseConfig, ScheduleConfig, Config
    from ibkr_datafetcher.types import SymbolConfig

    cfg = Config(GatewayConfig("127.0.0.1", 4012, 1),
                 SyncConfig(3, 30), DatabaseConfig("test.db"), ScheduleConfig(False, ""))
    mock_load_cfg.return_value = cfg
    mock_load_sym.return_value = [
        SymbolConfig(symbol="AAPL", name="Apple"),
        SymbolConfig(symbol="VIX", name="VIX", sec_type="IND", exchange="CBOE", what_to_show="MIDPOINT"),
    ]
    mock_client_inst = mock_client_cls.return_value
    mock_client_inst.connect.return_value = True
    mock_fetcher_inst = mock_fetcher_cls.return_value
    mock_fetcher_inst.sync_all.return_value = {
        "total_bars": 200, "symbols_processed": 2, "errors": [],
    }

    result = runner.invoke(main, ["sync"])
    assert result.exit_code == 0
    call_args = mock_fetcher_inst.sync_all.call_args
    syms = call_args[0][0]
    assert len(syms) == 2


def test_uc_p6_5_through_7_progress_panel():
    from ibkr_datafetcher.cli import _progress_printer
    from ibkr_datafetcher.types import SyncProgress

    prog = SyncProgress(
        symbol="AAPL", timeframe=Timeframe.D1, phase="fetching",
        current_range=3, total_ranges=12, bars_fetched=1200,
        elapsed_sec=150.0, eta_sec=150.0,
        rate_limiter_stats={
            "hist_requests": 5, "news_requests": 0,
            "utilization": 0.83, "total_waits": 0, "avg_wait_time": 0.0,
        },
    )
    _progress_printer(prog)


@mock.patch("ibkr_datafetcher.cli._load_config")
@mock.patch("ibkr_datafetcher.cli.Database")
def test_uc_p6_8_query_table(mock_db_cls, mock_load_cfg, runner):
    from ibkr_datafetcher.config import GatewayConfig, SyncConfig, DatabaseConfig, ScheduleConfig, Config

    cfg = Config(GatewayConfig("127.0.0.1", 4012, 1),
                 SyncConfig(3, 30), DatabaseConfig("test.db"), ScheduleConfig(False, ""))
    mock_load_cfg.return_value = cfg

    bar = KlineBar(symbol="AAPL", timeframe=Timeframe.D1, timestamp=1700000000,
                   open=150.0, high=152.0, low=149.0, close=151.0,
                   volume=1000000, bar_count=500,
                   bar_time=datetime(2023, 11, 14, tzinfo=timezone.utc))

    mock_db_inst = mock_db_cls.return_value
    mock_db_inst.query_klines.return_value = [bar]

    result = runner.invoke(main, ["query", "AAPL", "--timeframe", "1 day",
                                  "--limit", "10", "--format", "table"])
    assert result.exit_code == 0
    assert "AAPL" in result.output
    assert "150.00" in result.output


@mock.patch("ibkr_datafetcher.cli._load_config")
@mock.patch("ibkr_datafetcher.cli.Database")
def test_uc_p6_9_query_csv_output(mock_db_cls, mock_load_cfg, runner, tmp_path):
    from ibkr_datafetcher.config import GatewayConfig, SyncConfig, DatabaseConfig, ScheduleConfig, Config

    cfg = Config(GatewayConfig("127.0.0.1", 4012, 1),
                 SyncConfig(3, 30), DatabaseConfig("test.db"), ScheduleConfig(False, ""))
    mock_load_cfg.return_value = cfg

    bar = KlineBar(symbol="AAPL", timeframe=Timeframe.D1, timestamp=1700000000,
                   open=150.0, high=152.0, low=149.0, close=151.0,
                   volume=1000000, bar_count=500,
                   bar_time=datetime(2023, 11, 14, tzinfo=timezone.utc))
    mock_db_inst = mock_db_cls.return_value
    mock_db_inst.query_klines.return_value = [bar]

    out_file = str(tmp_path / "test.csv")
    result = runner.invoke(main, ["query", "AAPL", "--timeframe", "1 day",
                                  "--format", "csv", "--output", out_file])
    assert result.exit_code == 0
    assert os.path.exists(out_file)
    with open(out_file, encoding="utf-8") as f:
        content = f.read()
    assert "AAPL" in content
    assert "symbol" in content


@mock.patch("ibkr_datafetcher.cli._load_config")
@mock.patch("ibkr_datafetcher.cli.Database")
def test_uc_p6_10_query_json(mock_db_cls, mock_load_cfg, runner):
    from ibkr_datafetcher.config import GatewayConfig, SyncConfig, DatabaseConfig, ScheduleConfig, Config

    cfg = Config(GatewayConfig("127.0.0.1", 4012, 1),
                 SyncConfig(3, 30), DatabaseConfig("test.db"), ScheduleConfig(False, ""))
    mock_load_cfg.return_value = cfg

    bar = KlineBar(symbol="AAPL", timeframe=Timeframe.D1, timestamp=1700000000,
                   open=150.0, high=152.0, low=149.0, close=151.0,
                   volume=1000000, bar_count=500,
                   bar_time=datetime(2023, 11, 14, tzinfo=timezone.utc))
    mock_db_inst = mock_db_cls.return_value
    mock_db_inst.query_klines.return_value = [bar]

    result = runner.invoke(main, ["query", "AAPL", "--timeframe", "1 day", "--format", "json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert len(data) == 1
    assert data[0]["symbol"] == "AAPL"


@mock.patch("ibkr_datafetcher.cli._load_config")
@mock.patch("ibkr_datafetcher.cli.Database")
def test_uc_p6_11_query_time_range(mock_db_cls, mock_load_cfg, runner):
    from ibkr_datafetcher.config import GatewayConfig, SyncConfig, DatabaseConfig, ScheduleConfig, Config

    cfg = Config(GatewayConfig("127.0.0.1", 4012, 1),
                 SyncConfig(3, 30), DatabaseConfig("test.db"), ScheduleConfig(False, ""))
    mock_load_cfg.return_value = cfg
    mock_db_inst = mock_db_cls.return_value
    mock_db_inst.query_klines.return_value = []

    result = runner.invoke(main, ["query", "AAPL", "--timeframe", "1 day",
                                  "--from", "2024-01-01", "--to", "2024-06-01"])
    assert result.exit_code == 0
    call_kwargs = mock_db_inst.query_klines.call_args
    assert call_kwargs.kwargs.get("from_time") is not None or call_kwargs[1].get("from_time") is not None


@mock.patch("ibkr_datafetcher.cli._load_config")
@mock.patch("ibkr_datafetcher.cli.Database")
def test_uc_p6_12_status_all(mock_db_cls, mock_load_cfg, runner):
    from ibkr_datafetcher.config import GatewayConfig, SyncConfig, DatabaseConfig, ScheduleConfig, Config

    cfg = Config(GatewayConfig("127.0.0.1", 4012, 1),
                 SyncConfig(3, 30), DatabaseConfig("test.db"), ScheduleConfig(False, ""))
    mock_load_cfg.return_value = cfg

    status_row = SyncStatus(symbol="AAPL", timeframe=Timeframe.D1,
                            latest_bar_time=1700000000, bar_count=100,
                            synced_at=datetime(2024, 1, 1, tzinfo=timezone.utc))
    mock_db_inst = mock_db_cls.return_value
    mock_db_inst.get_all_sync_status.return_value = [status_row]

    result = runner.invoke(main, ["status"])
    assert result.exit_code == 0
    assert "AAPL" in result.output


@mock.patch("ibkr_datafetcher.cli._load_config")
@mock.patch("ibkr_datafetcher.cli.Database")
def test_uc_p6_13_status_symbol_filter(mock_db_cls, mock_load_cfg, runner):
    from ibkr_datafetcher.config import GatewayConfig, SyncConfig, DatabaseConfig, ScheduleConfig, Config

    cfg = Config(GatewayConfig("127.0.0.1", 4012, 1),
                 SyncConfig(3, 30), DatabaseConfig("test.db"), ScheduleConfig(False, ""))
    mock_load_cfg.return_value = cfg
    mock_db_inst = mock_db_cls.return_value
    mock_db_inst.get_sync_status.return_value = []

    result = runner.invoke(main, ["status", "--symbol", "AAPL"])
    assert result.exit_code == 0
    mock_db_inst.get_sync_status.assert_called_once_with("AAPL")


@mock.patch("ibkr_datafetcher.cli._load_config")
@mock.patch("ibkr_datafetcher.cli._load_symbols")
@mock.patch("ibkr_datafetcher.cli.IBKRClient")
@mock.patch("ibkr_datafetcher.cli.Database")
@mock.patch("ibkr_datafetcher.cli.NewsFetcher")
def test_uc_p6_14_news_command(mock_fetcher_cls, mock_db_cls, mock_client_cls,
                                mock_load_sym, mock_load_cfg, runner):
    from ibkr_datafetcher.config import GatewayConfig, SyncConfig, DatabaseConfig, ScheduleConfig, Config
    from ibkr_datafetcher.types import SymbolConfig

    cfg = Config(GatewayConfig("127.0.0.1", 4012, 1),
                 SyncConfig(3, 30), DatabaseConfig("test.db"), ScheduleConfig(False, ""))
    mock_load_cfg.return_value = cfg
    mock_load_sym.return_value = [
        SymbolConfig(symbol="AAPL", name="Apple"),
        SymbolConfig(symbol="MSFT", name="MSFT"),
    ]
    mock_client_inst = mock_client_cls.return_value
    mock_client_inst.connect.return_value = True

    mock_fetcher_inst = mock_fetcher_cls.return_value
    mock_fetcher_inst.fetch_symbol_news.return_value = {"symbol": "AAPL", "news_count": 5}

    result = runner.invoke(main, ["news", "--symbols", "AAPL,MSFT", "--days", "30"])
    assert result.exit_code == 0
    assert mock_fetcher_inst.fetch_symbol_news.call_count == 2


@mock.patch("ibkr_datafetcher.cli._load_config")
@mock.patch("ibkr_datafetcher.cli.IBKRClient")
def test_uc_p6_16_reconnect_connected(mock_client_cls, mock_load_cfg, runner):
    from ibkr_datafetcher.config import GatewayConfig, SyncConfig, DatabaseConfig, ScheduleConfig, Config

    cfg = Config(GatewayConfig("127.0.0.1", 4012, 1),
                 SyncConfig(3, 30), DatabaseConfig("test.db"), ScheduleConfig(False, ""))
    mock_load_cfg.return_value = cfg
    mock_client_inst = mock_client_cls.return_value
    mock_client_inst.is_connected.return_value = True

    result = runner.invoke(main, ["reconnect"])
    assert result.exit_code == 0
    assert "Already connected" in result.output


@mock.patch("ibkr_datafetcher.cli._load_config")
@mock.patch("ibkr_datafetcher.cli.IBKRClient")
def test_uc_p6_17_reconnect_not_connected(mock_client_cls, mock_load_cfg, runner):
    from ibkr_datafetcher.config import GatewayConfig, SyncConfig, DatabaseConfig, ScheduleConfig, Config

    cfg = Config(GatewayConfig("127.0.0.1", 4012, 1),
                 SyncConfig(3, 30), DatabaseConfig("test.db"), ScheduleConfig(False, ""))
    mock_load_cfg.return_value = cfg
    mock_client_inst = mock_client_cls.return_value
    mock_client_inst.is_connected.return_value = False
    mock_client_inst.reconnect.return_value = True

    result = runner.invoke(main, ["reconnect"])
    assert result.exit_code == 0
    assert "Reconnected" in result.output
    mock_client_inst.reconnect.assert_called_once()
