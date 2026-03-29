from __future__ import annotations

import logging
import signal
import threading
from typing import Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from ibkr_datafetcher.kline_fetcher import KlineFetcher
from ibkr_datafetcher.types import SymbolConfig, Timeframe

logger = logging.getLogger(__name__)


class Scheduler:
    def __init__(
        self,
        fetcher: KlineFetcher,
        symbols: list[SymbolConfig],
        timeframes: Optional[list[Timeframe]] = None,
    ):
        self._fetcher = fetcher
        self._symbols = symbols
        self._timeframes = timeframes
        self._scheduler: Optional[BackgroundScheduler] = None
        self._stop_event = threading.Event()

    def _sync_job(self) -> None:
        logger.info("Scheduler triggered sync_all")
        try:
            result = self._fetcher.sync_all(self._symbols, timeframes=self._timeframes)
            logger.info(
                "Sync complete: %d bars, %d processed, %d errors",
                result["total_bars"],
                result["symbols_processed"],
                len(result["errors"]),
            )
        except (ConnectionError, ValueError, OSError) as exc:
            logger.error("Sync job failed: %s", exc)

    def start(self, cron_expression: str) -> None:
        parts = cron_expression.strip().split()
        if len(parts) != 5:
            msg = f"invalid cron expression (need 5 fields): {cron_expression!r}"
            raise ValueError(msg)

        trigger = CronTrigger(
            minute=parts[0], hour=parts[1],
            day=parts[2], month=parts[3], day_of_week=parts[4],
        )

        self._scheduler = BackgroundScheduler()
        self._scheduler.add_job(self._sync_job, trigger, id="ibkr_sync")
        self._scheduler.start()
        logger.info("Scheduler started with cron: %s", cron_expression)

        self._stop_event.clear()
        is_main = threading.current_thread() is threading.main_thread()
        original_sigint = None
        if is_main:
            original_sigint = signal.getsignal(signal.SIGINT)

            def _on_signal(signum, frame):  # pylint: disable=unused-argument
                self.stop()

            signal.signal(signal.SIGINT, _on_signal)
        try:
            self._stop_event.wait()
        finally:
            if is_main and original_sigint is not None:
                signal.signal(signal.SIGINT, original_sigint)

    def stop(self) -> None:
        if self._scheduler is not None:
            self._scheduler.shutdown(wait=False)
            self._scheduler = None
            logger.info("Scheduler stopped")
        self._stop_event.set()

    def run_once(self) -> dict:
        return self._fetcher.sync_all(self._symbols, timeframes=self._timeframes)
