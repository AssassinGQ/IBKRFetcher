import time

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from croniter import croniter

from ibkr_datafetcher.config import SymbolConfig
from ibkr_datafetcher.kline_fetcher import KlineFetcher
from ibkr_datafetcher.types import Timeframe


class Scheduler:
    def __init__(
        self,
        fetcher: KlineFetcher,
        symbols: list[SymbolConfig],
        timeframes: list[Timeframe] | None = None,
    ):
        self._fetcher = fetcher
        self._symbols = symbols
        self._timeframes = timeframes
        self._scheduler = BackgroundScheduler()
        self._running = False

    def start(self, cron_expression: str) -> None:
        if not croniter.is_valid(cron_expression):
            raise ValueError(f"Invalid cron expression: {cron_expression}")

        trigger = CronTrigger.from_crontab(cron_expression)

        def job():
            self._fetcher.sync_all(self._symbols, self._timeframes)

        self._scheduler.add_job(job, trigger=trigger, id="sync_job", replace_existing=True)
        self._scheduler.start()
        self._running = True

        try:
            while self._running:
                time.sleep(1)
        except KeyboardInterrupt:
            pass

    def stop(self) -> None:
        self._running = False
        self._scheduler.shutdown(wait=False)

    def run_once(self) -> dict:
        return self._fetcher.sync_all(self._symbols, self._timeframes)
