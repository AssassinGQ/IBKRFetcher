from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from ibkr_datafetcher.db import Database
from ibkr_datafetcher.ibkr_client import IBKRClient
from ibkr_datafetcher.rate_limiter import RateLimiter
from ibkr_datafetcher.types import SymbolConfig, Timeframe

logger = logging.getLogger(__name__)

MAX_PROBE_ITERATIONS = 12


@dataclass(frozen=True, slots=True)
class TimeRange:
    start_time: datetime
    end_time: datetime


class BaseProber(ABC):
    def __init__(self, client: IBKRClient, rate_limiter: RateLimiter, db: Database):
        self._client = client
        self._rate_limiter = rate_limiter
        self._db = db

    @abstractmethod
    def get_pending_ranges(self, symbol_config: SymbolConfig, **kwargs) -> list[TimeRange]:
        ...


def _split_range(start: datetime, end: datetime, max_delta: timedelta) -> list[TimeRange]:
    if start >= end:
        return []
    ranges: list[TimeRange] = []
    cursor = end
    while cursor > start:
        seg_start = max(start, cursor - max_delta)
        ranges.append(TimeRange(start_time=seg_start, end_time=cursor))
        cursor = seg_start
    ranges.reverse()
    return ranges


class KlineProber(BaseProber):  # pylint: disable=too-few-public-methods

    def get_pending_ranges(
        self, symbol_config: SymbolConfig, timeframe: Timeframe = Timeframe.D1, **kwargs
    ) -> list[TimeRange]:
        now = datetime.now(tz=timezone.utc)
        sym = symbol_config.symbol
        tf_name = timeframe.name

        latest_ts = self._db.get_latest_bar_time(sym, tf_name)
        earliest_dt = self._probe_earliest_time(symbol_config, timeframe)
        if earliest_dt is None:
            return []

        if latest_ts is not None:
            latest_dt = datetime.fromtimestamp(latest_ts, tz=timezone.utc)
            start = latest_dt + timedelta(seconds=1)
        else:
            start = earliest_dt

        if start >= now:
            return []

        return _split_range(start, now, timeframe.max_duration_timedelta)

    def _probe_earliest_time(
        self, symbol_config: SymbolConfig, timeframe: Timeframe
    ) -> Optional[datetime]:
        sym = symbol_config.symbol
        tf_name = timeframe.name

        cached = self._db.get_earliest_time(sym, tf_name)
        if cached is not None:
            return datetime.fromtimestamp(cached, tz=timezone.utc)

        contract = self._client.make_contract(symbol_config)
        probe_end = datetime.now(tz=timezone.utc) - timedelta(days=30)
        earliest_found: Optional[datetime] = None

        for _ in range(MAX_PROBE_ITERATIONS):
            end_str = probe_end.strftime("%Y%m%d %H:%M:%S") + " UTC"
            self._rate_limiter.acquire(
                request_type="hist",
                symbol=sym,
                exchange=symbol_config.exchange,
                sec_type=symbol_config.sec_type,
            )
            try:
                bars = self._client.get_historical_bars(
                    contract, timeframe,
                    end_date_time=end_str,
                    duration=timeframe.ibkr_max_duration,
                    what_to_show=symbol_config.what_to_show,
                )
            except (ConnectionError, ValueError):
                break

            if not bars:
                break

            bar_time = bars[0].bar_time
            earliest_found = bar_time
            probe_end = bar_time - timedelta(seconds=1)

        if earliest_found is not None:
            self._db.set_earliest_time(sym, tf_name, int(earliest_found.timestamp()))
            time.sleep(0.05)

        return earliest_found


class NewsProber(BaseProber):  # pylint: disable=too-few-public-methods

    def get_pending_ranges(
        self, symbol_config: SymbolConfig, days: int = 30, **kwargs
    ) -> list[TimeRange]:
        now = datetime.now(tz=timezone.utc)
        sym = symbol_config.symbol

        latest_ts = self._db.get_latest_news_time(sym)
        if latest_ts is not None:
            latest_dt = datetime.fromtimestamp(latest_ts, tz=timezone.utc)
            if (now - latest_dt).total_seconds() < 60:
                return []
            return [TimeRange(start_time=latest_dt, end_time=now)]

        start = now - timedelta(days=days)
        return [TimeRange(start_time=start, end_time=now)]
