from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from unittest import mock

import pytest

from ibkr_datafetcher.db import Database
from ibkr_datafetcher.timeframe_prober import KlineProber, NewsProber, TimeRange, _split_range
from ibkr_datafetcher.types import KlineBar, Timeframe, SymbolConfig

AAPL = SymbolConfig(symbol="AAPL", name="Apple Inc.", sec_type="STK",
                     exchange="SMART", currency="USD")
VIX = SymbolConfig(symbol="VIX", name="VIX", sec_type="IND",
                    exchange="CBOE", currency="USD", what_to_show="MIDPOINT")


def _make_bar(sym: str, tf: Timeframe, ts: int) -> KlineBar:
    return KlineBar(
        symbol=sym, timeframe=tf, timestamp=ts,
        open=100.0, high=101.0, low=99.0, close=100.5,
        volume=1000.0, bar_count=10,
        bar_time=datetime.fromtimestamp(ts, tz=timezone.utc),
    )


@pytest.fixture
def db_inst(tmp_path):
    db = Database(str(tmp_path / "test.db"))
    yield db
    db.close()


@pytest.fixture
def mock_client():
    return mock.MagicMock()


@pytest.fixture
def mock_rl():
    return mock.MagicMock()


def test_uc_p5_1_empty_db_returns_full_range(db_inst, mock_client, mock_rl):
    now = datetime.now(tz=timezone.utc)
    earliest = now - timedelta(days=5)
    earliest_ts = int(earliest.timestamp())

    bars = [_make_bar("AAPL", Timeframe.D1, earliest_ts)]
    mock_client.get_historical_bars.side_effect = [bars, []]
    mock_client.make_contract.return_value = mock.MagicMock()

    prober = KlineProber(mock_client, mock_rl, db_inst)
    ranges = prober.get_pending_ranges(AAPL, timeframe=Timeframe.D1)

    assert len(ranges) >= 1
    assert ranges[0].start_time <= earliest + timedelta(seconds=1)
    assert ranges[-1].end_time >= now - timedelta(seconds=5)


def test_uc_p5_2_cached_returns_partial_range(db_inst, mock_client, mock_rl):
    now = datetime.now(tz=timezone.utc)
    cached_ts = int((now - timedelta(days=2)).timestamp())
    db_inst.insert_kline_bars([_make_bar("AAPL", Timeframe.D1, cached_ts)])
    time.sleep(0.1)

    earliest = now - timedelta(days=10)
    db_inst.set_earliest_time("AAPL", "D1", int(earliest.timestamp()))
    time.sleep(0.1)

    prober = KlineProber(mock_client, mock_rl, db_inst)
    ranges = prober.get_pending_ranges(AAPL, timeframe=Timeframe.D1)

    assert len(ranges) >= 1
    assert ranges[0].start_time >= datetime.fromtimestamp(cached_ts, tz=timezone.utc)


def test_uc_p5_3_fully_cached_returns_empty(db_inst, mock_client, mock_rl):
    now = datetime.now(tz=timezone.utc)
    future_ts = int((now + timedelta(seconds=10)).timestamp())
    db_inst.insert_kline_bars([_make_bar("AAPL", Timeframe.D1, future_ts)])
    time.sleep(0.1)

    db_inst.set_earliest_time("AAPL", "D1", int((now - timedelta(days=10)).timestamp()))
    time.sleep(0.1)

    prober = KlineProber(mock_client, mock_rl, db_inst)
    ranges = prober.get_pending_ranges(AAPL, timeframe=Timeframe.D1)

    assert ranges == []


def test_uc_p5_4_large_span_split_into_multiple(db_inst, mock_client, mock_rl):
    now = datetime.now(tz=timezone.utc)
    earliest = now - timedelta(days=400)
    db_inst.set_earliest_time("AAPL", "D1", int(earliest.timestamp()))
    time.sleep(0.1)

    prober = KlineProber(mock_client, mock_rl, db_inst)
    ranges = prober.get_pending_ranges(AAPL, timeframe=Timeframe.D1)

    assert len(ranges) >= 2


def test_uc_p5_5_each_range_within_max_duration():
    start = datetime(2020, 1, 1, tzinfo=timezone.utc)
    end = datetime(2023, 1, 1, tzinfo=timezone.utc)
    max_d = Timeframe.D1.max_duration_timedelta

    ranges = _split_range(start, end, max_d)
    for r in ranges:
        assert (r.end_time - r.start_time) <= max_d


def test_uc_p5_6_probe_cached_no_ibkr_calls(db_inst, mock_client, mock_rl):
    ts = int((datetime.now(tz=timezone.utc) - timedelta(days=100)).timestamp())
    db_inst.set_earliest_time("AAPL", "D1", ts)
    time.sleep(0.1)

    prober = KlineProber(mock_client, mock_rl, db_inst)
    result = prober._probe_earliest_time(AAPL, Timeframe.D1)

    assert result is not None
    mock_client.get_historical_bars.assert_not_called()


def test_uc_p5_7_probe_uncached_calls_ibkr(db_inst, mock_client, mock_rl):
    now = datetime.now(tz=timezone.utc)
    bar_ts = int((now - timedelta(days=60)).timestamp())
    bars = [_make_bar("AAPL", Timeframe.D1, bar_ts)]
    mock_client.get_historical_bars.side_effect = [bars, []]
    mock_client.make_contract.return_value = mock.MagicMock()

    prober = KlineProber(mock_client, mock_rl, db_inst)
    result = prober._probe_earliest_time(AAPL, Timeframe.D1)

    assert result is not None
    assert mock_client.get_historical_bars.call_count >= 1


def test_uc_p5_8_probe_calls_rate_limiter(db_inst, mock_client, mock_rl):
    bars = [_make_bar("AAPL", Timeframe.D1, 1000000)]
    mock_client.get_historical_bars.side_effect = [bars, []]
    mock_client.make_contract.return_value = mock.MagicMock()

    prober = KlineProber(mock_client, mock_rl, db_inst)
    prober._probe_earliest_time(AAPL, Timeframe.D1)

    assert mock_rl.acquire.call_count >= 1
    for call in mock_rl.acquire.call_args_list:
        assert call.kwargs.get("request_type", call.args[0] if call.args else "hist") == "hist"


def test_uc_p5_9_probe_continues_when_data_stops_when_empty(db_inst, mock_client, mock_rl):
    now = datetime.now(tz=timezone.utc)
    ts1 = int((now - timedelta(days=60)).timestamp())
    ts2 = int((now - timedelta(days=120)).timestamp())
    bars1 = [_make_bar("AAPL", Timeframe.D1, ts1)]
    bars2 = [_make_bar("AAPL", Timeframe.D1, ts2)]

    mock_client.get_historical_bars.side_effect = [bars1, bars2, []]
    mock_client.make_contract.return_value = mock.MagicMock()

    prober = KlineProber(mock_client, mock_rl, db_inst)
    result = prober._probe_earliest_time(AAPL, Timeframe.D1)

    assert result is not None
    assert mock_client.get_historical_bars.call_count == 3


def test_uc_p5_10_probe_writes_to_db(db_inst, mock_client, mock_rl):
    ts = int((datetime.now(tz=timezone.utc) - timedelta(days=60)).timestamp())
    bars = [_make_bar("AAPL", Timeframe.D1, ts)]
    mock_client.get_historical_bars.side_effect = [bars, []]
    mock_client.make_contract.return_value = mock.MagicMock()

    prober = KlineProber(mock_client, mock_rl, db_inst)
    prober._probe_earliest_time(AAPL, Timeframe.D1)
    time.sleep(0.15)

    cached = db_inst.get_earliest_time("AAPL", "D1")
    assert cached is not None
    assert cached == ts


def test_uc_p5_11_second_call_uses_cache(db_inst, mock_client, mock_rl):
    ts = int((datetime.now(tz=timezone.utc) - timedelta(days=60)).timestamp())
    bars = [_make_bar("AAPL", Timeframe.D1, ts)]
    mock_client.get_historical_bars.side_effect = [bars, []]
    mock_client.make_contract.return_value = mock.MagicMock()

    prober = KlineProber(mock_client, mock_rl, db_inst)
    prober._probe_earliest_time(AAPL, Timeframe.D1)
    time.sleep(0.15)

    mock_client.get_historical_bars.reset_mock()
    result2 = prober._probe_earliest_time(AAPL, Timeframe.D1)
    assert result2 is not None
    mock_client.get_historical_bars.assert_not_called()


def test_uc_p5_12_all_empty_returns_none(db_inst, mock_client, mock_rl):
    mock_client.get_historical_bars.return_value = []
    mock_client.make_contract.return_value = mock.MagicMock()

    prober = KlineProber(mock_client, mock_rl, db_inst)
    result = prober._probe_earliest_time(AAPL, Timeframe.D1)

    assert result is None


def test_uc_p5_13_news_no_local_returns_range(db_inst, mock_client, mock_rl):
    prober = NewsProber(mock_client, mock_rl, db_inst)
    ranges = prober.get_pending_ranges(AAPL, days=30)

    assert len(ranges) == 1
    span = ranges[0].end_time - ranges[0].start_time
    assert abs(span.total_seconds() - 30 * 86400) < 60


def test_uc_p5_14_news_with_local_returns_delta(db_inst, mock_client, mock_rl):
    from ibkr_datafetcher.types import NewsItem
    now = datetime.now(tz=timezone.utc)
    old_ts = int((now - timedelta(days=5)).timestamp())
    db_inst.insert_news([NewsItem(
        article_id="test1", symbol="AAPL", headline="h",
        provider_code="BRFG", timestamp=old_ts,
    )])
    time.sleep(0.1)

    prober = NewsProber(mock_client, mock_rl, db_inst)
    ranges = prober.get_pending_ranges(AAPL, days=30)

    assert len(ranges) == 1
    assert ranges[0].start_time <= datetime.fromtimestamp(old_ts, tz=timezone.utc) + timedelta(seconds=1)


def test_uc_p5_15_news_fully_fresh_returns_empty(db_inst, mock_client, mock_rl):
    from ibkr_datafetcher.types import NewsItem
    now = datetime.now(tz=timezone.utc)
    fresh_ts = int(now.timestamp())
    db_inst.insert_news([NewsItem(
        article_id="test2", symbol="AAPL", headline="h",
        provider_code="BRFG", timestamp=fresh_ts,
    )])
    time.sleep(0.1)

    prober = NewsProber(mock_client, mock_rl, db_inst)
    ranges = prober.get_pending_ranges(AAPL, days=30)

    assert ranges == []
