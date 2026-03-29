from __future__ import annotations

from collections.abc import Callable
from typing import Optional

from ibkr_datafetcher.kline_fetcher import KlineFetcher
from ibkr_datafetcher.types import SymbolConfig, Timeframe


class Scheduler:
    """Placeholder scheduler - full implementation in Stage 7."""

    def __init__(
        self,
        fetcher: KlineFetcher,
        symbols: list[SymbolConfig],
        timeframes: Optional[list[Timeframe]] = None,
    ):
        self._fetcher = fetcher
        self._symbols = symbols
        self._timeframes = timeframes

    def start(self, cron_expression: str) -> None:
        raise NotImplementedError("Scheduler not yet implemented (Stage 7)")

    def stop(self) -> None:
        raise NotImplementedError("Scheduler not yet implemented (Stage 7)")
