from __future__ import annotations

import threading
import time
from unittest import mock

import pytest

from ibkr_datafetcher.scheduler import Scheduler
from ibkr_datafetcher.types import SymbolConfig, Timeframe

AAPL = SymbolConfig(symbol="AAPL", name="Apple")


@pytest.fixture
def mock_fetcher():
    f = mock.MagicMock()
    f.sync_all.return_value = {"total_bars": 0, "symbols_processed": 0, "errors": []}
    return f


def test_uc_p7_1_construct(mock_fetcher):
    sched = Scheduler(mock_fetcher, [AAPL], timeframes=[Timeframe.D1])
    assert sched._fetcher is mock_fetcher
    assert sched._symbols == [AAPL]
    assert sched._timeframes == [Timeframe.D1]


def test_uc_p7_2_start_parses_cron_and_registers_job(mock_fetcher):
    sched = Scheduler(mock_fetcher, [AAPL])

    def _run():
        sched.start("*/5 * * * *")

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    time.sleep(0.5)

    assert sched._scheduler is not None
    jobs = sched._scheduler.get_jobs()
    assert len(jobs) == 1
    assert jobs[0].id == "ibkr_sync"

    sched.stop()
    t.join(timeout=3)


def test_uc_p7_3_cron_triggers_sync_all(mock_fetcher):
    sched = Scheduler(mock_fetcher, [AAPL])

    def _run():
        sched.start("* * * * *")

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    time.sleep(0.5)

    sched._sync_job()
    mock_fetcher.sync_all.assert_called_once()

    sched.stop()
    t.join(timeout=3)


def test_uc_p7_4_stop_shuts_down(mock_fetcher):
    sched = Scheduler(mock_fetcher, [AAPL])

    def _run():
        sched.start("*/5 * * * *")

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    time.sleep(0.5)

    sched.stop()
    t.join(timeout=3)

    assert sched._scheduler is None


def test_uc_p7_5_run_once(mock_fetcher):
    sched = Scheduler(mock_fetcher, [AAPL], timeframes=[Timeframe.D1])
    result = sched.run_once()

    mock_fetcher.sync_all.assert_called_once_with([AAPL], timeframes=[Timeframe.D1])
    assert "total_bars" in result
