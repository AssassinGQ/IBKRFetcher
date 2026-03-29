"""Deterministic fake data generators for the mock IBKR gateway."""

import hashlib
import math
from datetime import datetime, timedelta
from dataclasses import dataclass
from typing import Optional


@dataclass
class FakeBar:
    date: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    average: float
    bar_count: int


@dataclass
class FakeNewsItem:
    time: str
    provider_code: str
    article_id: str
    headline: str


@dataclass
class FakeSmartComponent:
    bit_number: int
    exchange: str
    exchange_letter: str


def _seed_hash(symbol: str, timeframe: str, idx: int) -> float:
    """Generate a deterministic float in [0,1) from seed parameters."""
    raw = f"{symbol}:{timeframe}:{idx}".encode()
    h = hashlib.md5(raw).hexdigest()
    return int(h[:8], 16) / 0xFFFFFFFF


def _base_price(symbol: str) -> float:
    """Return a base price for known symbols."""
    prices = {
        "AAPL": 185.0, "SPY": 510.0, "MSFT": 420.0, "GOOGL": 170.0,
        "00700": 380.0, "ES": 5200.0, "NQ": 18000.0,
        "VIX": 18.0, "VIX3M": 20.0, "VIX9D": 16.0, "VIX6M": 22.0,
        "VIX1Y": 23.0, "VXN": 20.0, "VXD": 15.0, "VXO": 17.0,
        "DX": 104.0,
        "EUR": 1.08, "GBP": 1.27, "JPY": 0.0067,
    }
    return prices.get(symbol, 100.0)


def _volatility_range(symbol: str) -> tuple[float, float]:
    """Return (min, max) for volatility indices."""
    ranges = {
        "VIX": (12.0, 35.0), "VIX3M": (15.0, 30.0),
        "VIX9D": (10.0, 40.0), "VIX6M": (16.0, 28.0),
        "VIX1Y": (17.0, 27.0), "VXN": (14.0, 32.0),
        "VXD": (10.0, 25.0), "VXO": (11.0, 30.0),
        "DX": (100.0, 108.0),
    }
    return ranges.get(symbol, (10.0, 30.0))


def _is_volatility_index(symbol: str) -> bool:
    return symbol in (
        "VIX", "VIX3M", "VIX9D", "VIX6M", "VIX1Y", "VXN", "VXD", "VXO", "DX"
    )


def _parse_duration_seconds(duration_str: str) -> int:
    """Parse IBKR duration string to seconds."""
    parts = duration_str.strip().split()
    if len(parts) != 2:
        return 86400
    val, unit = int(parts[0]), parts[1].upper()
    multipliers = {"S": 1, "D": 86400, "W": 604800, "M": 2592000, "Y": 31536000}
    return val * multipliers.get(unit, 86400)


def _parse_bar_size_seconds(bar_size: str) -> int:
    """Parse IBKR bar size string to seconds."""
    bar_size = bar_size.strip().lower()
    mapping = {
        "1 secs": 1, "5 secs": 5, "10 secs": 10, "15 secs": 15, "30 secs": 30,
        "1 min": 60, "2 mins": 120, "3 mins": 180, "5 mins": 300,
        "10 mins": 600, "15 mins": 900, "20 mins": 1200, "30 mins": 1800,
        "1 hour": 3600, "2 hours": 7200, "3 hours": 10800,
        "4 hours": 14400, "8 hours": 28800,
        "1 day": 86400, "1 week": 604800, "1 month": 2592000,
    }
    return mapping.get(bar_size, 86400)


def generate_bars(
    symbol: str,
    bar_size: str,
    duration_str: str,
    end_dt: Optional[datetime] = None,
    what_to_show: str = "TRADES",
    format_date: int = 2,
) -> list[FakeBar]:
    """Generate deterministic OHLCV bars for a given symbol and timeframe."""
    if end_dt is None:
        end_dt = datetime.now().replace(second=0, microsecond=0)

    duration_secs = _parse_duration_seconds(duration_str)
    bar_secs = _parse_bar_size_seconds(bar_size)

    if bar_secs <= 0:
        bar_secs = 86400
    num_bars = min(duration_secs // bar_secs, 5000)
    if num_bars <= 0:
        num_bars = 1

    start_dt = end_dt - timedelta(seconds=duration_secs)
    base = _base_price(symbol)
    is_vol = _is_volatility_index(symbol)

    bars = []
    for i in range(num_bars):
        bar_dt = start_dt + timedelta(seconds=bar_secs * (i + 1))

        seed = _seed_hash(symbol, bar_size, i)
        seed2 = _seed_hash(symbol, bar_size, i + 10000)
        seed3 = _seed_hash(symbol, bar_size, i + 20000)

        if is_vol:
            vmin, vmax = _volatility_range(symbol)
            mid = (vmin + vmax) / 2
            amplitude = (vmax - vmin) / 2
            price = mid + amplitude * math.sin(seed * math.pi * 2 + i * 0.1)
            price = max(vmin, min(vmax, price))
            spread = price * 0.005
        else:
            change_pct = (seed - 0.5) * 0.02
            price = base * (1 + change_pct + math.sin(i * 0.05) * 0.01)
            spread = price * 0.01

        o = round(price, 4)
        c = round(price + (seed2 - 0.5) * spread, 4)
        h = round(max(o, c) + abs(seed3) * spread * 0.5, 4)
        low = round(min(o, c) - abs(1 - seed3) * spread * 0.5, 4)

        if is_vol:
            vol = round(seed * 10000, 0)
        else:
            vol = round(seed * 1000000 + 100000, 0)
        avg = round((o + h + low + c) / 4, 4)
        bc = max(1, int(seed2 * 500))

        if format_date == 2:
            date_str = bar_dt.strftime("%Y%m%d  %H:%M:%S") if bar_secs < 86400 \
                else bar_dt.strftime("%Y%m%d")
        else:
            date_str = str(int(bar_dt.timestamp()))

        bars.append(FakeBar(
            date=date_str, open=o, high=h, low=low,
            close=c, volume=vol, average=avg, bar_count=bc,
        ))

    return bars


FAKE_NEWS_PROVIDERS = [
    ("BRFG", "Briefing.com General"),
    ("BRFUPDN", "Briefing.com Analyst Actions"),
    ("DJNL", "Dow Jones Newsletters"),
]


def generate_news(
    con_id: int,
    symbol: str = "AAPL",
    count: int = 5,
    start_dt: Optional[datetime] = None,
    end_dt: Optional[datetime] = None,
) -> list[FakeNewsItem]:
    """Generate deterministic fake news items."""
    if end_dt is None:
        end_dt = datetime.now()
    if start_dt is None:
        start_dt = end_dt - timedelta(days=7)

    headlines = [
        f"{symbol} Reports Strong Quarterly Earnings",
        f"Analyst Upgrades {symbol} to Buy Rating",
        f"{symbol} Announces New Product Launch",
        f"Market Analysis: {symbol} Shows Bullish Pattern",
        f"{symbol} Expands Operations in Asia Pacific",
        f"Breaking: {symbol} CEO Discusses Growth Strategy",
        f"{symbol} Stock Hits 52-Week High",
        f"Insider Trading Alert for {symbol}",
        f"{symbol} Dividend Announcement",
        f"Technical Analysis: {symbol} Support and Resistance",
    ]

    providers = ["BRFG", "BRFUPDN", "DJNL"]
    items = []
    time_step = (end_dt - start_dt) / max(count, 1)

    for i in range(min(count, len(headlines))):
        t = start_dt + time_step * (i + 1)
        provider = providers[i % len(providers)]
        article_id = f"{provider}${con_id}{i + 1:04d}"
        items.append(FakeNewsItem(
            time=t.strftime("%Y-%m-%d %H:%M:%S.0"),
            provider_code=provider,
            article_id=article_id,
            headline=headlines[i],
        ))

    return items


def generate_news_bulletins() -> list[dict]:
    """Generate fake news bulletin items."""
    return [
        {
            "msgId": 1001,
            "msgType": 1,
            "message": "Market Advisory: Regular trading hours",
            "exchange": "SMART",
        },
        {
            "msgId": 1002,
            "msgType": 2,
            "message": "System Status: All exchanges operational",
            "exchange": "SMART",
        },
    ]


def generate_smart_components(exchange_code: str) -> list[FakeSmartComponent]:
    """Generate fake smart components for a BBO exchange code."""
    components_map = {
        "BOBO": [
            FakeSmartComponent(1, "NYSE", "N"),
            FakeSmartComponent(2, "ARCA", "P"),
            FakeSmartComponent(4, "BATS", "Z"),
        ],
        "AMBO": [
            FakeSmartComponent(1, "AMEX", "A"),
            FakeSmartComponent(2, "NYSE", "N"),
        ],
        "SMT": [
            FakeSmartComponent(1, "SMART", "S"),
            FakeSmartComponent(2, "IEX", "V"),
            FakeSmartComponent(4, "LTSE", "L"),
        ],
    }
    return components_map.get(exchange_code, [
        FakeSmartComponent(1, "UNKNOWN", "U"),
    ])


KNOWN_CONTRACTS: dict[str, dict] = {
    "AAPL:STK:SMART:USD": {"conId": 265598, "exchange": "SMART", "primaryExchange": "NASDAQ"},
    "AAPL:STK:NASDAQ:USD": {"conId": 265598, "exchange": "NASDAQ", "primaryExchange": "NASDAQ"},
    "SPY:STK:SMART:USD": {"conId": 756733, "exchange": "SMART", "primaryExchange": "ARCA"},
    "MSFT:STK:SMART:USD": {"conId": 272093, "exchange": "SMART", "primaryExchange": "NASDAQ"},
    "GOOGL:STK:SMART:USD": {"conId": 208813720, "exchange": "SMART", "primaryExchange": "NASDAQ"},
    "00700:STK:SEHK:HKD": {"conId": 44938836, "exchange": "SEHK", "primaryExchange": "SEHK"},
    "700:STK:SEHK:HKD": {"conId": 44938836, "exchange": "SEHK", "primaryExchange": "SEHK"},
    "ES:FUT:GLOBEX:USD": {"conId": 495512572, "exchange": "GLOBEX", "primaryExchange": ""},
    "VIX:IND:CBOE:USD": {"conId": 13455763, "exchange": "CBOE", "primaryExchange": ""},
    "VIX3M:IND:CBOE:USD": {"conId": 300591602, "exchange": "CBOE", "primaryExchange": ""},
    "VIX9D:IND:CBOE:USD": {"conId": 329498498, "exchange": "CBOE", "primaryExchange": ""},
    "VIX6M:IND:CBOE:USD": {"conId": 329498499, "exchange": "CBOE", "primaryExchange": ""},
    "VIX1Y:IND:CBOE:USD": {"conId": 329498500, "exchange": "CBOE", "primaryExchange": ""},
    "VXN:IND:CBOE:USD": {"conId": 38687989, "exchange": "CBOE", "primaryExchange": ""},
    "VXD:IND:CBOE:USD": {"conId": 38687991, "exchange": "CBOE", "primaryExchange": ""},
    "VXO:IND:CBOE:USD": {"conId": 38688001, "exchange": "CBOE", "primaryExchange": ""},
    "DX:IND:NYBOT:USD": {"conId": 12087817, "exchange": "NYBOT", "primaryExchange": ""},
    "EUR:CASH:IDEALPRO:USD": {"conId": 12087792, "exchange": "IDEALPRO", "primaryExchange": ""},
}


def lookup_contract(symbol: str, sec_type: str, exchange: str, currency: str) -> Optional[dict]:
    """Look up a contract by its key fields and return contract details."""
    key = f"{symbol}:{sec_type}:{exchange}:{currency}"
    return KNOWN_CONTRACTS.get(key)
