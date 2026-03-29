"""UC-P1-1 through UC-P1-11: types and Timeframe duration behavior."""

from datetime import datetime, timedelta

import pytest

from ibkr_datafetcher.types import (
    KlineBar,
    NewsItem,
    SymbolConfig,
    SyncProgress,
    SyncStatus,
    Timeframe,
    _parse_ibkr_duration,
)


def test_uc_p1_1_timeframe_enum_members():
    names = {tf.name for tf in Timeframe}
    expected = {
        "S5",
        "S10",
        "S15",
        "S30",
        "M1",
        "M2",
        "M3",
        "M5",
        "M10",
        "M15",
        "M20",
        "M30",
        "H1",
        "H2",
        "H3",
        "H4",
        "H8",
        "D1",
        "W1",
        "MN1",
    }
    assert names == expected
    assert len(Timeframe) == 20


def test_uc_p1_2_ibkr_bar_size_matches_value():
    assert Timeframe.S5.ibkr_bar_size == "5 secs"
    assert Timeframe.MN1.ibkr_bar_size == "1 month"


def test_uc_p1_3_ibkr_max_duration_mapping():
    assert Timeframe.S5.ibkr_max_duration == "2000 S"
    assert Timeframe.S30.ibkr_max_duration == "16000 S"
    assert Timeframe.M1.ibkr_max_duration == "1 D"
    assert Timeframe.M2.ibkr_max_duration == "2 D"
    assert Timeframe.M15.ibkr_max_duration == "2 W"
    assert Timeframe.D1.ibkr_max_duration == "1 Y"
    assert Timeframe.MN1.ibkr_max_duration == "1 Y"


def test_uc_p1_4_max_duration_timedelta_seconds():
    assert Timeframe.S10.max_duration_timedelta == timedelta(seconds=4000)


def test_uc_p1_5_max_duration_timedelta_day_week_month_year():
    assert Timeframe.M1.max_duration_timedelta == timedelta(days=1)
    assert Timeframe.M2.max_duration_timedelta == timedelta(days=2)
    assert Timeframe.M3.max_duration_timedelta == timedelta(weeks=1)
    assert Timeframe.M15.max_duration_timedelta == timedelta(weeks=2)
    assert Timeframe.M20.max_duration_timedelta == timedelta(days=30)
    assert Timeframe.H1.max_duration_timedelta == timedelta(days=30)
    assert Timeframe.D1.max_duration_timedelta == timedelta(days=365)
    assert Timeframe.W1.max_duration_timedelta == timedelta(days=365)


def test_uc_p1_6_kline_bar_dataclass():
    bt = datetime(2024, 1, 2, 15, 30, tzinfo=None)
    bar = KlineBar(
        symbol="AAPL",
        timeframe=Timeframe.M5,
        timestamp=1_700_000_000,
        open=100.0,
        high=101.0,
        low=99.0,
        close=100.5,
        volume=1_000_000.0,
        bar_count=1,
        bar_time=bt,
    )
    assert bar.symbol == "AAPL"
    assert bar.timeframe is Timeframe.M5
    assert bar.volume == 1_000_000.0


def test_uc_p1_7_news_item_dataclass():
    n = NewsItem(
        article_id="a1",
        symbol=None,
        headline="h",
        provider_code="BRFG",
        timestamp=1,
    )
    assert n.symbol is None
    assert n.headline == "h"


def test_uc_p1_8_sync_status_dataclass():
    sa = datetime(2024, 1, 1, 0, 0, 0)
    s = SyncStatus(
        symbol="SPY",
        timeframe=Timeframe.D1,
        latest_bar_time=99,
        bar_count=10,
        synced_at=sa,
    )
    assert s.latest_bar_time == 99
    assert s.synced_at == sa


def test_uc_p1_9_sync_progress_and_symbol_config_defaults():
    p = SyncProgress(
        symbol="MSFT",
        timeframe=Timeframe.H1,
        phase="backfill",
        current_range=1,
        total_ranges=5,
        bars_fetched=100,
        elapsed_sec=1.5,
        eta_sec=10.0,
        rate_limiter_stats={"waits": 2},
    )
    assert p.eta_sec == 10.0
    assert p.rate_limiter_stats["waits"] == 2
    sc = SymbolConfig(symbol="X", name="Y")
    assert sc.sec_type == "STK"
    assert sc.exchange == "SMART"
    assert sc.currency == "USD"
    assert sc.what_to_show == "TRADES"


def test_uc_p1_10_all_timeframes_parse_max_duration():
    for tf in Timeframe:
        td = tf.max_duration_timedelta
        assert isinstance(td, timedelta)
        assert td.total_seconds() > 0


def test_uc_p1_11_parse_ibkr_duration_invalid():
    with pytest.raises(ValueError):
        _parse_ibkr_duration("bogus")
