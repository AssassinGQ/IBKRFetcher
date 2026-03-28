from datetime import datetime, timedelta, timezone
from typing import Optional

from ibkr_datafetcher.config import SymbolConfig
from ibkr_datafetcher.db import Database
from ibkr_datafetcher.ibkr_client import IBKRClient
from ibkr_datafetcher.rate_limiter import RateLimiter
from ibkr_datafetcher.types import Timeframe


class TimeRange:
    def __init__(self, start: datetime, end: datetime):
        self.start = start
        self.end = end

    def __repr__(self):
        return f"TimeRange({self.start} -> {self.end})"


class KlineProber:
    def __init__(
        self,
        ibkr_client: IBKRClient,
        rate_limiter: RateLimiter,
        db: Database,
    ):
        self._client = ibkr_client
        self._rate_limiter = rate_limiter
        self._db = db

    def get_pending_ranges(
        self,
        symbol_config: SymbolConfig,
        timeframe: Timeframe,
    ) -> list[TimeRange]:
        latest_ts = self._db.get_latest_bar_time(symbol_config.symbol, timeframe.name)
        if latest_ts is None:
            earliest_time = self._probe_earliest_time(symbol_config, timeframe)
            if earliest_time is None:
                now = datetime.now(timezone.utc)
                end = now - timeframe.td
                start = end - self._max_duration_for_timeframe(timeframe)
                return [TimeRange(start, end)]
            latest_ts = int(earliest_time.timestamp())
            end = datetime.fromtimestamp(latest_ts, tz=timezone.utc)
            start = earliest_time
            return [TimeRange(start, end)] if start < end else []

        latest_dt = datetime.fromtimestamp(latest_ts, tz=timezone.utc)
        now = datetime.now(timezone.utc)
        end = now - timeframe.td
        if latest_dt >= end:
            return []

        start = latest_dt
        return [TimeRange(start, end)]

    def _probe_earliest_time(
        self,
        symbol_config: SymbolConfig,
        timeframe: Timeframe,
    ) -> Optional[datetime]:
        tf_name = timeframe.name
        cached_ts = self._db.get_earliest_bar_time(symbol_config.symbol, tf_name)
        if cached_ts is not None:
            return datetime.fromtimestamp(cached_ts, tz=timezone.utc)

        try:
            contract = self._client.make_contract(symbol_config)
            self._rate_limiter.acquire("hist", symbol_config.symbol)
            bars = self._client.get_historical_bars(
                contract=contract,
                timeframe=timeframe,
                end_date_time="",
                duration=timeframe.value.max_duration,
                what_to_show=symbol_config.what_to_show,
            )
            if bars:
                earliest = bars[0].date
                self._db.set_earliest_bar_time(symbol_config.symbol, tf_name, int(earliest.timestamp()))
                return earliest
            return None
        except Exception:
            return None

    def _max_duration_for_timeframe(self, timeframe: Timeframe) -> timedelta:
        return timeframe.max_duration_timedelta


class NewsProber:
    def __init__(
        self,
        ibkr_client: IBKRClient,
        rate_limiter: RateLimiter,
        db: Database,
    ):
        self._client = ibkr_client
        self._rate_limiter = rate_limiter
        self._db = db

    def get_pending_ranges(
        self,
        symbol_config: SymbolConfig,
        days: int = 30,
    ) -> list[TimeRange]:
        latest_ts = self._db.get_latest_news_time(symbol_config.symbol)
        now = datetime.now(timezone.utc)

        if latest_ts is None:
            start = now - timedelta(days=days)
            return [TimeRange(start, now)]

        latest_dt = datetime.fromtimestamp(latest_ts, tz=timezone.utc)
        if latest_dt >= now:
            return []

        start = latest_dt
        return [TimeRange(start, now)]
