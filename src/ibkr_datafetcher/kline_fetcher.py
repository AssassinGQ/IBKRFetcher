from __future__ import annotations

import logging
import time
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Optional

from ibkr_datafetcher.db import Database
from ibkr_datafetcher.ibkr_client import IBKRClient
from ibkr_datafetcher.rate_limiter import RateLimiter
from ibkr_datafetcher.timeframe_prober import KlineProber
from ibkr_datafetcher.types import SymbolConfig, SyncProgress, SyncStatus, Timeframe

logger = logging.getLogger(__name__)


class KlineFetcher:
    def __init__(self, client: IBKRClient, rate_limiter: RateLimiter, db: Database):
        self._client = client
        self._rate_limiter = rate_limiter
        self._db = db
        self._prober = KlineProber(client, rate_limiter, db)

    def sync_symbol(
        self,
        symbol_config: SymbolConfig,
        timeframe: Timeframe,
        progress_callback: Optional[Callable[[SyncProgress], None]] = None,
    ) -> dict:
        sym = symbol_config.symbol
        contract = self._client.make_contract(symbol_config)
        ranges = self._prober.get_pending_ranges(symbol_config, timeframe=timeframe)
        total = len(ranges)

        if total == 0:
            return {
                "symbol": sym,
                "timeframe": timeframe.name,
                "bars_fetched": 0,
                "ranges_processed": 0,
            }

        bars_fetched = 0
        t0 = time.monotonic()

        for idx, tr in enumerate(ranges):
            end_str = tr.end_time.strftime("%Y%m%d %H:%M:%S") + " UTC"
            dur_secs = (tr.end_time - tr.start_time).total_seconds()
            duration = self._estimate_duration(dur_secs, timeframe)

            self._rate_limiter.acquire(
                request_type="hist",
                symbol=sym,
                exchange=symbol_config.exchange,
                sec_type=symbol_config.sec_type,
            )
            bars = self._client.get_historical_bars(
                contract, timeframe,
                end_date_time=end_str,
                duration=duration,
                what_to_show=symbol_config.what_to_show,
            )

            if bars:
                self._db.insert_kline_bars(bars)
                bars_fetched += len(bars)

                latest = max(bars, key=lambda b: b.timestamp)
                now = datetime.now(tz=timezone.utc)
                self._db.update_sync_status(SyncStatus(
                    symbol=sym,
                    timeframe=timeframe,
                    latest_bar_time=latest.timestamp,
                    bar_count=bars_fetched,
                    synced_at=now,
                ))

            if progress_callback is not None:
                elapsed = time.monotonic() - t0
                done = idx + 1
                per_range = elapsed / done if done else 0
                remaining = total - done
                eta = per_range * remaining if per_range > 0 else None
                progress_callback(SyncProgress(
                    symbol=sym,
                    timeframe=timeframe,
                    phase="fetching",
                    current_range=done,
                    total_ranges=total,
                    bars_fetched=bars_fetched,
                    elapsed_sec=elapsed,
                    eta_sec=eta,
                    rate_limiter_stats=self._rate_limiter.get_stats(),
                ))

        return {
            "symbol": sym,
            "timeframe": timeframe.name,
            "bars_fetched": bars_fetched,
            "ranges_processed": total,
        }

    def sync_all(
        self,
        symbols: list[SymbolConfig],
        timeframes: Optional[list[Timeframe]] = None,
        progress_callback: Optional[Callable[[SyncProgress], None]] = None,
    ) -> dict:
        tfs = timeframes if timeframes is not None else list(Timeframe)
        total_bars = 0
        processed = 0
        errors: list[str] = []

        for sc in symbols:
            for tf in tfs:
                try:
                    result = self.sync_symbol(sc, tf, progress_callback)
                    total_bars += result["bars_fetched"]
                    processed += 1
                except (ConnectionError, ValueError, OSError) as e:
                    msg = f"{sc.symbol}/{tf.name}: {e}"
                    logger.warning("sync error: %s", msg)
                    errors.append(msg)

        return {
            "total_bars": total_bars,
            "symbols_processed": processed,
            "errors": errors,
        }

    @staticmethod
    def _estimate_duration(seconds: float, timeframe: Timeframe) -> str:
        td = timeframe.max_duration_timedelta
        if seconds >= td.total_seconds():
            return timeframe.ibkr_max_duration
        if seconds >= 86400:
            days = max(1, int(seconds / 86400))
            return f"{days} D"
        return timeframe.ibkr_max_duration
