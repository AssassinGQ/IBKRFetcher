from __future__ import annotations

import os
from datetime import datetime, timezone
from unittest import mock

import pytest
from click.testing import CliRunner

from ibkr_datafetcher.cli import main
from ibkr_datafetcher.db import Database
from ibkr_datafetcher.types import SyncStatus, Timeframe

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
def test_uc_p6_8_query_time_range_with_timeframe(mock_db_cls, mock_load_cfg, runner):
    from ibkr_datafetcher.config import GatewayConfig, SyncConfig, DatabaseConfig, ScheduleConfig, Config

    cfg = Config(GatewayConfig("127.0.0.1", 4012, 1),
                 SyncConfig(3, 30), DatabaseConfig("test.db"), ScheduleConfig(False, ""))
    mock_load_cfg.return_value = cfg

    mock_db_inst = mock_db_cls.return_value
    mock_db_inst.get_time_range.return_value = (1700000000, 1704000000)

    result = runner.invoke(main, ["query", "AAPL", "--timeframe", "1 day"])
    assert result.exit_code == 0
    assert "2023-11-14 ~ 2023-12-31" in result.output
    mock_db_inst.get_time_range.assert_called_once_with("AAPL", "D1")


@mock.patch("ibkr_datafetcher.cli._load_config")
@mock.patch("ibkr_datafetcher.cli.Database")
def test_uc_p6_9_query_all_timeframes(mock_db_cls, mock_load_cfg, runner):
    from ibkr_datafetcher.config import GatewayConfig, SyncConfig, DatabaseConfig, ScheduleConfig, Config

    cfg = Config(GatewayConfig("127.0.0.1", 4012, 1),
                 SyncConfig(3, 30), DatabaseConfig("test.db"), ScheduleConfig(False, ""))
    mock_load_cfg.return_value = cfg

    mock_db_inst = mock_db_cls.return_value
    mock_db_inst.get_timeframes_for_symbol.return_value = ["D1", "H1"]
    mock_db_inst.get_time_range.side_effect = [
        (1700000000, 1704000000),
        (1700000000, 1702000000)
    ]

    result = runner.invoke(main, ["query", "AAPL"])
    assert result.exit_code == 0
    assert "D1:" in result.output
    assert "2023-11-14 ~ 2023-12-31" in result.output
    assert "H1:" in result.output
    assert "11-14" in result.output
    mock_db_inst.get_timeframes_for_symbol.assert_called_once_with("AAPL")


@mock.patch("ibkr_datafetcher.cli._load_config")
@mock.patch("ibkr_datafetcher.cli.Database")
def test_uc_p6_10_query_with_timeframe_no_data(mock_db_cls, mock_load_cfg, runner):
    from ibkr_datafetcher.config import GatewayConfig, SyncConfig, DatabaseConfig, ScheduleConfig, Config

    cfg = Config(GatewayConfig("127.0.0.1", 4012, 1),
                 SyncConfig(3, 30), DatabaseConfig("test.db"), ScheduleConfig(False, ""))
    mock_load_cfg.return_value = cfg

    mock_db_inst = mock_db_cls.return_value
    mock_db_inst.get_time_range.return_value = (None, None)

    result = runner.invoke(main, ["query", "AAPL", "--timeframe", "1 day"])
    assert result.exit_code == 0
    assert "No data found." in result.output


@mock.patch("ibkr_datafetcher.cli._load_config")
@mock.patch("ibkr_datafetcher.cli.Database")
def test_uc_p6_11_query_no_timeframe_no_data(mock_db_cls, mock_load_cfg, runner):
    from ibkr_datafetcher.config import GatewayConfig, SyncConfig, DatabaseConfig, ScheduleConfig, Config

    cfg = Config(GatewayConfig("127.0.0.1", 4012, 1),
                 SyncConfig(3, 30), DatabaseConfig("test.db"), ScheduleConfig(False, ""))
    mock_load_cfg.return_value = cfg
    mock_db_inst = mock_db_cls.return_value
    mock_db_inst.get_timeframes_for_symbol.return_value = []

    result = runner.invoke(main, ["query", "AAPL"])
    assert result.exit_code == 0
    assert "No data found." in result.output


@mock.patch("ibkr_datafetcher.cli._load_config")
@mock.patch("ibkr_datafetcher.cli.Database")
def test_uc_p6_11b_query_unknown_timeframe(mock_db_cls, mock_load_cfg, runner):
    from ibkr_datafetcher.config import GatewayConfig, SyncConfig, DatabaseConfig, ScheduleConfig, Config

    cfg = Config(GatewayConfig("127.0.0.1", 4012, 1),
                 SyncConfig(3, 30), DatabaseConfig("test.db"), ScheduleConfig(False, ""))
    mock_load_cfg.return_value = cfg

    result = runner.invoke(main, ["query", "AAPL", "--timeframe", "bogus"])
    assert result.exit_code != 0
    assert "Unknown timeframe: bogus" in result.output


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
def test_uc_p6_16_reconnect_success(mock_client_cls, mock_load_cfg, runner):
    from ibkr_datafetcher.config import GatewayConfig, SyncConfig, DatabaseConfig, ScheduleConfig, Config

    cfg = Config(GatewayConfig("127.0.0.1", 4012, 1),
                 SyncConfig(3, 30), DatabaseConfig("test.db"), ScheduleConfig(False, ""))
    mock_load_cfg.return_value = cfg
    mock_client_inst = mock_client_cls.return_value
    mock_client_inst.connect.return_value = True

    result = runner.invoke(main, ["reconnect"])
    assert result.exit_code == 0
    assert "Connected." in result.output
    mock_client_inst.connect.assert_called_once()


@mock.patch("ibkr_datafetcher.cli._load_config")
@mock.patch("ibkr_datafetcher.cli.IBKRClient")
def test_uc_p6_17_reconnect_failure(mock_client_cls, mock_load_cfg, runner):
    from ibkr_datafetcher.config import GatewayConfig, SyncConfig, DatabaseConfig, ScheduleConfig, Config

    cfg = Config(GatewayConfig("127.0.0.1", 4012, 1),
                 SyncConfig(3, 30), DatabaseConfig("test.db"), ScheduleConfig(False, ""))
    mock_load_cfg.return_value = cfg
    mock_client_inst = mock_client_cls.return_value
    mock_client_inst.connect.return_value = False

    result = runner.invoke(main, ["reconnect"])
    assert result.exit_code == 0
    assert "FAILED." in result.output
