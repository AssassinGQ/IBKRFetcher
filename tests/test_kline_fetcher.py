from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from unittest import mock

import pytest

from ibkr_datafetcher.db import Database
from ibkr_datafetcher.kline_fetcher import KlineFetcher
from ibkr_datafetcher.types import KlineBar, SymbolConfig, SyncProgress, Timeframe

AAPL = SymbolConfig(symbol="AAPL", name="Apple", sec_type="STK",
                     exchange="SMART", currency="USD")
VIX = SymbolConfig(symbol="VIX", name="VIX", sec_type="IND",
                    exchange="CBOE", currency="USD", what_to_show="MIDPOINT")
MSFT = SymbolConfig(symbol="MSFT", name="MSFT", sec_type="STK",
                     exchange="SMART", currency="USD")


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
    c = mock.MagicMock()
    c.make_contract.return_value = mock.MagicMock()
    return c


@pytest.fixture
def mock_rl():
    rl = mock.MagicMock()
    rl.get_stats.return_value = {
        "hist_requests": 0, "news_requests": 0,
        "total_waits": 0, "avg_wait_time": 0.0, "utilization": 0.0,
    }
    return rl


def _seed_earliest(db_inst, sym, tf_name, days_ago=200):
    ts = int((datetime.now(tz=timezone.utc) - timedelta(days=days_ago)).timestamp())
    db_inst.set_earliest_time(sym, tf_name, ts)
    time.sleep(0.1)
    return ts


def test_uc_p5_16_full_chain(db_inst, mock_client, mock_rl):
    _seed_earliest(db_inst, "AAPL", "D1", 10)

    now = datetime.now(tz=timezone.utc)
    bar_ts = int((now - timedelta(hours=1)).timestamp())
    bars = [_make_bar("AAPL", Timeframe.D1, bar_ts)]
    mock_client.get_historical_bars.return_value = bars

    fetcher = KlineFetcher(mock_client, mock_rl, db_inst)
    result = fetcher.sync_symbol(AAPL, Timeframe.D1)

    assert result["symbol"] == "AAPL"
    assert result["bars_fetched"] > 0
    assert result["ranges_processed"] > 0

    mock_rl.acquire.assert_called()
    acquire_calls = mock_rl.acquire.call_args_list
    for call in acquire_calls:
        assert call.kwargs.get("request_type", "hist") == "hist"

    time.sleep(0.1)
    stored = db_inst.query_klines("AAPL", "D1")
    assert len(stored) > 0


def test_uc_p5_17_no_pending_returns_zero(db_inst, mock_client, mock_rl):
    now = datetime.now(tz=timezone.utc)
    recent = int(now.timestamp())
    db_inst.insert_kline_bars([_make_bar("AAPL", Timeframe.D1, recent)])
    time.sleep(0.1)
    db_inst.set_earliest_time("AAPL", "D1", int((now - timedelta(days=10)).timestamp()))
    time.sleep(0.1)

    fetcher = KlineFetcher(mock_client, mock_rl, db_inst)
    result = fetcher.sync_symbol(AAPL, Timeframe.D1)

    assert result["bars_fetched"] == 0
    assert result["ranges_processed"] == 0


def test_uc_p5_18_progress_callback_called(db_inst, mock_client, mock_rl):
    _seed_earliest(db_inst, "AAPL", "D1", 10)

    bar_ts = int((datetime.now(tz=timezone.utc) - timedelta(hours=1)).timestamp())
    mock_client.get_historical_bars.return_value = [_make_bar("AAPL", Timeframe.D1, bar_ts)]

    cb = mock.MagicMock()
    fetcher = KlineFetcher(mock_client, mock_rl, db_inst)
    fetcher.sync_symbol(AAPL, Timeframe.D1, progress_callback=cb)

    assert cb.call_count >= 1
    prog = cb.call_args_list[0][0][0]
    assert isinstance(prog, SyncProgress)
    assert prog.phase == "fetching"
    assert prog.current_range >= 1
    assert prog.total_ranges >= 1
    assert isinstance(prog.rate_limiter_stats, dict)


def test_uc_p5_19_eta_decreases_over_ranges(db_inst, mock_client, mock_rl):
    _seed_earliest(db_inst, "AAPL", "M1", 3)

    bar_ts = int((datetime.now(tz=timezone.utc) - timedelta(hours=1)).timestamp())
    mock_client.get_historical_bars.return_value = [_make_bar("AAPL", Timeframe.M1, bar_ts)]

    etas = []
    def _cb(p: SyncProgress):
        if p.eta_sec is not None:
            etas.append(p.eta_sec)

    fetcher = KlineFetcher(mock_client, mock_rl, db_inst)
    fetcher.sync_symbol(AAPL, Timeframe.M1, progress_callback=_cb)

    if len(etas) >= 2:
        assert etas[-1] <= etas[0]


def test_uc_p5_20_result_dict_shape(db_inst, mock_client, mock_rl):
    _seed_earliest(db_inst, "AAPL", "D1", 10)

    bar_ts = int((datetime.now(tz=timezone.utc) - timedelta(hours=1)).timestamp())
    mock_client.get_historical_bars.return_value = [_make_bar("AAPL", Timeframe.D1, bar_ts)]

    fetcher = KlineFetcher(mock_client, mock_rl, db_inst)
    result = fetcher.sync_symbol(AAPL, Timeframe.D1)

    assert "symbol" in result
    assert "timeframe" in result
    assert "bars_fetched" in result
    assert "ranges_processed" in result


def test_uc_p5_21_ind_passes_midpoint(db_inst, mock_client, mock_rl):
    _seed_earliest(db_inst, "VIX", "D1", 10)

    bar_ts = int((datetime.now(tz=timezone.utc) - timedelta(hours=1)).timestamp())
    mock_client.get_historical_bars.return_value = [_make_bar("VIX", Timeframe.D1, bar_ts)]

    fetcher = KlineFetcher(mock_client, mock_rl, db_inst)
    fetcher.sync_symbol(VIX, Timeframe.D1)

    for call in mock_client.get_historical_bars.call_args_list:
        assert call.kwargs.get("what_to_show") == "MIDPOINT"


def test_uc_p5_22_sync_all_traverses_all(db_inst, mock_client, mock_rl):
    for sym in ("AAPL", "MSFT"):
        for tf in (Timeframe.D1, Timeframe.H1):
            _seed_earliest(db_inst, sym, tf.name, 10)

    bar_ts = int((datetime.now(tz=timezone.utc) - timedelta(hours=1)).timestamp())
    mock_client.get_historical_bars.return_value = [_make_bar("X", Timeframe.D1, bar_ts)]

    fetcher = KlineFetcher(mock_client, mock_rl, db_inst)
    result = fetcher.sync_all([AAPL, MSFT], timeframes=[Timeframe.D1, Timeframe.H1])

    assert result["symbols_processed"] == 4


def test_uc_p5_23_none_timeframes_uses_all(db_inst, mock_client, mock_rl):
    mock_client.get_historical_bars.return_value = []

    fetcher = KlineFetcher(mock_client, mock_rl, db_inst)
    with mock.patch.object(fetcher, 'sync_symbol', return_value={
        "symbol": "AAPL", "timeframe": "D1", "bars_fetched": 0, "ranges_processed": 0
    }) as m:
        fetcher.sync_all([AAPL], timeframes=None)
        assert m.call_count == len(Timeframe)


def test_uc_p5_24_single_failure_does_not_stop_others(db_inst, mock_client, mock_rl):
    for sym in ("AAPL", "MSFT"):
        _seed_earliest(db_inst, sym, "D1", 10)

    bar_ts = int((datetime.now(tz=timezone.utc) - timedelta(hours=1)).timestamp())
    call_count = [0]

    def side_effect(*args, **kwargs):
        call_count[0] += 1
        if call_count[0] <= 1:
            raise ConnectionError("test error")
        return [_make_bar("MSFT", Timeframe.D1, bar_ts)]

    mock_client.get_historical_bars.side_effect = side_effect

    fetcher = KlineFetcher(mock_client, mock_rl, db_inst)
    result = fetcher.sync_all([AAPL, MSFT], timeframes=[Timeframe.D1])

    assert len(result["errors"]) >= 1
    assert result["symbols_processed"] >= 1


def test_uc_p5_25_sync_all_result_shape(db_inst, mock_client, mock_rl):
    mock_client.get_historical_bars.return_value = []

    fetcher = KlineFetcher(mock_client, mock_rl, db_inst)
    result = fetcher.sync_all([], timeframes=[Timeframe.D1])

    assert "total_bars" in result
    assert "symbols_processed" in result
    assert "errors" in result
