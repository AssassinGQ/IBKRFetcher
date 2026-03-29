from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum


def _parse_ibkr_duration(dur: str) -> timedelta:
    norm = re.sub(r"\s+", "", dur.strip().upper())
    m = re.fullmatch(r"(\d+)([SDWMY])", norm)
    if not m:
        msg = f"invalid IBKR duration: {dur!r}"
        raise ValueError(msg)
    n = int(m.group(1))
    u = m.group(2)
    if u == "S":
        return timedelta(seconds=n)
    if u == "D":
        return timedelta(days=n)
    if u == "W":
        return timedelta(weeks=n)
    if u == "M":
        return timedelta(days=30 * n)
    if u == "Y":
        return timedelta(days=365 * n)
    raise AssertionError(u)


class Timeframe(Enum):
    S5 = "5 secs"
    S10 = "10 secs"
    S15 = "15 secs"
    S30 = "30 secs"
    M1 = "1 min"
    M2 = "2 mins"
    M3 = "3 mins"
    M5 = "5 mins"
    M10 = "10 mins"
    M15 = "15 mins"
    M20 = "20 mins"
    M30 = "30 mins"
    H1 = "1 hour"
    H2 = "2 hours"
    H3 = "3 hours"
    H4 = "4 hours"
    H8 = "8 hours"
    D1 = "1 day"
    W1 = "1 week"
    MN1 = "1 month"

    @property
    def ibkr_bar_size(self) -> str:
        return self.value

    @property
    def ibkr_max_duration(self) -> str:
        return _TIMEFRAME_MAX_DURATION[self]

    @property
    def max_duration_timedelta(self) -> timedelta:
        return _parse_ibkr_duration(self.ibkr_max_duration)


_TIMEFRAME_MAX_DURATION: dict[Timeframe, str] = {
    Timeframe.S5: "2000 S",
    Timeframe.S10: "4000 S",
    Timeframe.S15: "8000 S",
    Timeframe.S30: "16000 S",
    Timeframe.M1: "1 D",
    Timeframe.M2: "2 D",
    Timeframe.M3: "1 W",
    Timeframe.M5: "1 W",
    Timeframe.M10: "1 W",
    Timeframe.M15: "2 W",
    Timeframe.M20: "1 M",
    Timeframe.M30: "1 M",
    Timeframe.H1: "1 M",
    Timeframe.H2: "1 M",
    Timeframe.H3: "1 M",
    Timeframe.H4: "1 M",
    Timeframe.H8: "1 M",
    Timeframe.D1: "1 Y",
    Timeframe.W1: "1 Y",
    Timeframe.MN1: "1 Y",
}


@dataclass(frozen=True, slots=True)
class KlineBar:
    symbol: str
    timeframe: Timeframe
    timestamp: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    bar_count: int
    bar_time: datetime


@dataclass(frozen=True, slots=True)
class NewsItem:
    article_id: str
    symbol: str | None
    headline: str
    provider_code: str
    timestamp: int


@dataclass(frozen=True, slots=True)
class SyncStatus:
    symbol: str
    timeframe: Timeframe
    latest_bar_time: int
    bar_count: int
    synced_at: datetime


@dataclass(frozen=True, slots=True)
class SyncProgress:
    symbol: str
    timeframe: Timeframe
    phase: str
    current_range: int
    total_ranges: int
    bars_fetched: int
    elapsed_sec: float
    eta_sec: float | None
    rate_limiter_stats: dict


@dataclass(frozen=True, slots=True)
class SymbolConfig:
    symbol: str
    name: str
    sec_type: str = "STK"
    exchange: str = "SMART"
    currency: str = "USD"
    what_to_show: str = "TRADES"
