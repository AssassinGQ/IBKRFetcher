import pytest
from datetime import datetime, timedelta

from ibkr_datafetcher.types import (
    Timeframe,
    KlineBar,
    NewsItem,
    SyncStatus,
    SyncProgress,
    SymbolConfig,
)


class TestTimeframe:
    def test_all_timeframes_have_ibkr_bar_size(self):
        for tf in Timeframe:
            assert tf.ibkr_bar_size is not None
            assert len(tf.ibkr_bar_size) > 0

    def test_all_timeframes_have_ibkr_max_duration(self):
        for tf in Timeframe:
            assert tf.ibkr_max_duration is not None
            assert len(tf.ibkr_max_duration) > 0

    def test_all_timeframes_have_max_duration_timedelta(self):
        for tf in Timeframe:
            td = tf.max_duration_timedelta
            assert isinstance(td, timedelta)
            assert td.total_seconds() > 0

    def test_all_timeframes_have_td_property(self):
        for tf in Timeframe:
            td = tf.td
            assert isinstance(td, timedelta)
            assert td.total_seconds() > 0

    def test_common_timeframes_values(self):
        assert Timeframe.M1.ibkr_bar_size == "1 min"
        assert Timeframe.D1.ibkr_bar_size == "1 day"
        assert Timeframe.W1.ibkr_bar_size == "1 week"
        assert Timeframe.MN1.ibkr_bar_size == "1 month"

    def test_timeframe_td_for_seconds(self):
        assert Timeframe.S5.td == timedelta(seconds=5)
        assert Timeframe.S30.td == timedelta(seconds=30)

    def test_timeframe_td_for_minutes(self):
        assert Timeframe.M1.td == timedelta(minutes=1)
        assert Timeframe.M30.td == timedelta(minutes=30)

    def test_timeframe_td_for_hours(self):
        assert Timeframe.H1.td == timedelta(hours=1)
        assert Timeframe.H8.td == timedelta(hours=8)


class TestKlineBar:
    def test_klinebar_creation(self):
        bar = KlineBar(
            symbol="AAPL",
            timeframe="1 min",
            timestamp=1700000000,
            open=150.0,
            high=151.0,
            low=149.0,
            close=150.5,
            volume=1000000.0,
            bar_count=100,
            bar_time=datetime(2023, 11, 14, 20, 0),
        )
        assert bar.symbol == "AAPL"
        assert bar.timeframe == "1 min"
        assert bar.timestamp == 1700000000
        assert bar.open == 150.0
        assert bar.high == 151.0
        assert bar.low == 149.0
        assert bar.close == 150.5
        assert bar.volume == 1000000.0
        assert bar.bar_count == 100

    def test_klinebar_defaults(self):
        bar = KlineBar(
            symbol="AAPL",
            timeframe="1 min",
            timestamp=1700000000,
            open=150.0,
            high=151.0,
            low=149.0,
            close=150.5,
            volume=1000000.0,
            bar_count=100,
            bar_time=datetime.now(),
        )
        assert bar.symbol is not None


class TestNewsItem:
    def test_newsitem_creation(self):
        news = NewsItem(
            article_id="BRFG$12345",
            symbol="AAPL",
            headline="Apple announces new product",
            provider_code="BRFG",
            timestamp=1700000000,
        )
        assert news.article_id == "BRFG$12345"
        assert news.symbol == "AAPL"
        assert news.headline == "Apple announces new product"
        assert news.provider_code == "BRFG"
        assert news.timestamp == 1700000000

    def test_newsitem_without_symbol(self):
        news = NewsItem(
            article_id="BRFG$99999",
            symbol=None,
            headline="Market news",
            provider_code="DJNL",
            timestamp=1700000000,
        )
        assert news.article_id == "BRFG$99999"
        assert news.symbol is None


class TestSyncStatus:
    def test_syncstatus_creation(self):
        status = SyncStatus(
            symbol="AAPL",
            timeframe="1 min",
            latest_bar_time=1700000000,
            bar_count=1000,
            synced_at=datetime.now(),
        )
        assert status.symbol == "AAPL"
        assert status.timeframe == "1 min"
        assert status.latest_bar_time == 1700000000
        assert status.bar_count == 1000


class TestSyncProgress:
    def test_syncprogress_creation(self):
        progress = SyncProgress(
            symbol="AAPL",
            timeframe="1 min",
            phase="fetching",
            current_range=5,
            total_ranges=10,
            bars_fetched=500,
            elapsed_sec=120.0,
            eta_sec=120.0,
        )
        assert progress.symbol == "AAPL"
        assert progress.phase == "fetching"
        assert progress.current_range == 5
        assert progress.total_ranges == 10
        assert progress.bars_fetched == 500

    def test_syncprogress_with_none_eta(self):
        progress = SyncProgress(
            symbol="AAPL",
            timeframe="1 min",
            phase="probing",
            current_range=0,
            total_ranges=10,
            bars_fetched=0,
            elapsed_sec=5.0,
            eta_sec=None,
        )
        assert progress.eta_sec is None


class TestSymbolConfig:
    def test_symbolconfig_defaults(self):
        config = SymbolConfig(symbol="AAPL", name="Apple Inc.")
        assert config.symbol == "AAPL"
        assert config.name == "Apple Inc."
        assert config.sec_type == "STK"
        assert config.exchange == "SMART"
        assert config.currency == "USD"
        assert config.what_to_show == "TRADES"

    def test_symbolconfig_custom(self):
        config = SymbolConfig(
            symbol="AAPL",
            name="Apple Inc.",
            sec_type="STK",
            exchange="NASDAQ",
            currency="USD",
            what_to_show="MIDPOINT",
        )
        assert config.exchange == "NASDAQ"
        assert config.what_to_show == "MIDPOINT"

    def test_symbolconfig_forex(self):
        config = SymbolConfig(
            symbol="EURUSD",
            name="Euro/USD",
            sec_type="CASH",
            exchange="IDEALPRO",
            currency="USD",
        )
        assert config.sec_type == "CASH"
        assert config.exchange == "IDEALPRO"

    def test_symbolconfig_index(self):
        config = SymbolConfig(
            symbol="VIX",
            name="CBOE Volatility Index",
            sec_type="IND",
            exchange="CBOE",
            currency="USD",
            what_to_show="MIDPOINT",
        )
        assert config.sec_type == "IND"
        assert config.exchange == "CBOE"
        assert config.what_to_show == "MIDPOINT"
