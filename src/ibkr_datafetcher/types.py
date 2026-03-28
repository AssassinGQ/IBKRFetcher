from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional


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
        duration_map = {
            "S5": "120 S",
            "S10": "120 S",
            "S15": "120 S",
            "S30": "120 S",
            "M1": "60 S",
            "M2": "120 S",
            "M3": "180 S",
            "M5": "60 S",
            "M10": "120 S",
            "M15": "180 S",
            "M20": "240 S",
            "M30": "360 S",
            "H1": "1 D",
            "H2": "1 D",
            "H3": "1 D",
            "H4": "1 D",
            "H8": "1 D",
            "D1": "1 W",
            "W1": "1 Y",
            "MN1": "1 Y",
        }
        return duration_map[self.name]

    @property
    def max_duration_timedelta(self) -> timedelta:
        duration_td_map = {
            "S5": timedelta(seconds=120),
            "S10": timedelta(seconds=120),
            "S15": timedelta(seconds=120),
            "S30": timedelta(seconds=120),
            "M1": timedelta(seconds=60),
            "M2": timedelta(seconds=120),
            "M3": timedelta(seconds=180),
            "M5": timedelta(minutes=60),
            "M10": timedelta(minutes=120),
            "M15": timedelta(minutes=180),
            "M20": timedelta(minutes=240),
            "M30": timedelta(minutes=360),
            "H1": timedelta(days=1),
            "H2": timedelta(days=1),
            "H3": timedelta(days=1),
            "H4": timedelta(days=1),
            "H8": timedelta(days=1),
            "D1": timedelta(weeks=1),
            "W1": timedelta(days=365),
            "MN1": timedelta(days=365),
        }
        return duration_td_map[self.name]

    @property
    def td(self) -> timedelta:
        value = self.value
        if "sec" in value:
            seconds = int(value.split()[0])
            return timedelta(seconds=seconds)
        elif "min" in value:
            minutes = int(value.split()[0])
            return timedelta(minutes=minutes)
        elif "hour" in value:
            hours = int(value.split()[0])
            return timedelta(hours=hours)
        elif "day" in value:
            return timedelta(days=1)
        elif "week" in value:
            return timedelta(weeks=1)
        elif "month" in value:
            return timedelta(days=30)
        return timedelta()


@dataclass
class KlineBar:
    symbol: str
    timeframe: str
    timestamp: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    bar_count: int
    bar_time: datetime


@dataclass
class NewsItem:
    article_id: str
    symbol: Optional[str]
    headline: str
    provider_code: str
    timestamp: int


@dataclass
class SyncStatus:
    symbol: str
    timeframe: str
    latest_bar_time: int
    bar_count: int
    synced_at: datetime


@dataclass
class SyncProgress:
    symbol: str
    timeframe: str
    phase: str
    current_range: int
    total_ranges: int
    bars_fetched: int
    elapsed_sec: float
    eta_sec: Optional[float]
    rate_limiter_stats: dict = field(default_factory=dict)


@dataclass
class SymbolConfig:
    symbol: str
    name: str
    sec_type: str = "STK"
    exchange: str = "SMART"
    currency: str = "USD"
    what_to_show: str = "TRADES"
