import pytest
from unittest.mock import MagicMock, patch
from click.testing import CliRunner

from ibkr_datafetcher.cli import (
    main,
    load_symbols,
    parse_timeframes,
    format_progress,
)
from ibkr_datafetcher.config import Config
from ibkr_datafetcher.types import SymbolConfig, SyncProgress, Timeframe


class TestLoadSymbols:
    def test_load_symbols_no_filter(self):
        cfg = Config()
        cfg.sync.symbols = [
            SymbolConfig(symbol="AAPL", name="Apple", sec_type="STK",
                         exchange="SMART", currency="USD"),
            SymbolConfig(symbol="TSLA", name="Tesla", sec_type="STK",
                         exchange="SMART", currency="USD"),
        ]
        result = load_symbols(None, cfg)
        assert len(result) == 2

    def test_load_symbols_with_filter(self):
        cfg = Config()
        cfg.sync.symbols = [
            SymbolConfig(symbol="AAPL", name="Apple", sec_type="STK",
                         exchange="SMART", currency="USD"),
            SymbolConfig(symbol="TSLA", name="Tesla", sec_type="STK",
                         exchange="SMART", currency="USD"),
        ]
        result = load_symbols("AAPL", cfg)
        assert len(result) == 1
        assert result[0].symbol == "AAPL"

    def test_load_symbols_with_multiple_filter(self):
        cfg = Config()
        cfg.sync.symbols = [
            SymbolConfig(symbol="AAPL", name="Apple", sec_type="STK",
                         exchange="SMART", currency="USD"),
            SymbolConfig(symbol="TSLA", name="Tesla", sec_type="STK",
                         exchange="SMART", currency="USD"),
            SymbolConfig(symbol="MSFT", name="Microsoft", sec_type="STK",
                         exchange="SMART", currency="USD"),
        ]
        result = load_symbols("AAPL,TSLA", cfg)
        assert len(result) == 2


class TestParseTimeframes:
    def test_parse_timeframes_none(self):
        result = parse_timeframes(None)
        assert result == []

    def test_parse_timeframes_empty(self):
        result = parse_timeframes("")
        assert result == []

    def test_parse_timeframes_single(self):
        result = parse_timeframes("D1")
        assert result == [Timeframe.D1]

    def test_parse_timeframes_multiple(self):
        result = parse_timeframes("D1,H1,M5")
        assert result == [Timeframe.D1, Timeframe.H1, Timeframe.M5]

    def test_parse_timeframes_invalid_ignored(self):
        result = parse_timeframes("D1,INVALID,M5")
        assert result == [Timeframe.D1, Timeframe.M5]

    def test_parse_timeframes_all_invalid(self):
        result = parse_timeframes("INVALID")
        assert result == []


class TestFormatProgress:
    def test_format_progress_basic(self):
        progress = SyncProgress(
            symbol="AAPL",
            timeframe="D1",
            phase="fetching",
            current_range=3,
            total_ranges=10,
            bars_fetched=500,
            elapsed_sec=0.0,
            eta_sec=120.0,
        )
        rate_stats = {
            "hist": {"used": 5, "limit": 6},
            "news": {"used": 2, "limit": 3},
        }
        result = format_progress(progress, rate_stats)
        assert "AAPL" in result
        assert "D1" in result
        assert "3/10" in result
        assert "500" in result
        assert "hist 5/6" in result
        assert "news 2/3" in result
        assert "ETA" in result

    def test_format_progress_zero_ranges(self):
        progress = SyncProgress(
            symbol="AAPL",
            timeframe="H1",
            phase="probing",
            current_range=0,
            total_ranges=0,
            bars_fetched=0,
            elapsed_sec=0.0,
            eta_sec=None,
        )
        rate_stats = {}
        result = format_progress(progress, rate_stats)
        assert "AAPL" in result
        assert "ETA" not in result


class TestCliSync:
    @patch("ibkr_datafetcher.cli.load_config")
    def test_sync_no_symbols(self, mock_load):
        mock_cfg = MagicMock()
        mock_cfg.sync.symbols = []
        mock_load.return_value = mock_cfg

        runner = CliRunner()
        result = runner.invoke(main, ["sync", "--symbols=AAPL", "--config=nonexistent.yaml"])
        assert result.exit_code == 1
        assert "没有找到匹配的标的" in result.output

    @patch("ibkr_datafetcher.cli.load_config")
    def test_sync_invalid_timeframe(self, mock_load):
        mock_cfg = MagicMock()
        mock_cfg.sync.symbols = [
            SymbolConfig(symbol="AAPL", name="Apple", sec_type="STK",
                         exchange="SMART", currency="USD"),
        ]
        mock_load.return_value = mock_cfg

        runner = CliRunner()
        result = runner.invoke(main, [
            "sync", "--symbols=AAPL", "--timeframes=INVALID", "--config=nonexistent.yaml"
        ])
        assert result.exit_code == 1
        assert "没有找到匹配的周期" in result.output

    @patch("ibkr_datafetcher.cli.load_config")
    def test_sync_config_load_error(self, mock_load):
        mock_load.side_effect = FileNotFoundError("Config not found")

        runner = CliRunner()
        result = runner.invoke(main, ["sync", "--config=nonexistent.yaml"])
        assert result.exit_code == 1
        assert "配置加载失败" in result.output


class TestCliQuery:
    @patch("ibkr_datafetcher.cli.load_config")
    def test_query_invalid_timeframe(self, mock_load):
        mock_cfg = MagicMock()
        mock_load.return_value = mock_cfg

        runner = CliRunner()
        result = runner.invoke(main, ["query", "AAPL", "--timeframe=INVALID", "--config=nonexistent.yaml"])
        assert result.exit_code == 1
        assert "无效的时间周期" in result.output


class TestCliStatus:
    @patch("ibkr_datafetcher.cli.load_config")
    def test_status_config_error(self, mock_load):
        mock_load.side_effect = RuntimeError("Error")

        runner = CliRunner()
        result = runner.invoke(main, ["status", "--config=nonexistent.yaml"])
        assert result.exit_code == 1
        assert "配置加载失败" in result.output


class TestCliNews:
    @patch("ibkr_datafetcher.cli.load_config")
    def test_news_no_symbols(self, mock_load):
        mock_cfg = MagicMock()
        mock_cfg.sync.symbols = []
        mock_load.return_value = mock_cfg

        runner = CliRunner()
        result = runner.invoke(main, ["news", "--symbols=AAPL", "--config=nonexistent.yaml"])
        assert result.exit_code == 1
        assert "没有找到匹配的标的" in result.output


class TestCliReconnect:
    @patch("ibkr_datafetcher.cli.load_config")
    def test_reconnect_config_error(self, mock_load):
        mock_load.side_effect = RuntimeError("Error")

        runner = CliRunner()
        result = runner.invoke(main, ["reconnect", "--config=nonexistent.yaml"])
        assert result.exit_code == 1
        assert "配置加载失败" in result.output
