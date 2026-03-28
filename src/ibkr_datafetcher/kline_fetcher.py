from datetime import datetime, timezone
from typing import Callable, Optional

from ibkr_datafetcher.config import SymbolConfig
from ibkr_datafetcher.db import Database
from ibkr_datafetcher.ibkr_client import IBKRClient
from ibkr_datafetcher.rate_limiter import RateLimiter
from ibkr_datafetcher.timeframe_prober import KlineProber
from ibkr_datafetcher.types import SyncProgress, SyncStatus, Timeframe


class KlineFetcher:
    def __init__(
        self,
        ibkr_client: IBKRClient,
        rate_limiter: RateLimiter,
        db: Database,
    ):
        self._client = ibkr_client
        self._rate_limiter = rate_limiter
        self._db = db
        self._prober = KlineProber(ibkr_client, rate_limiter, db)

    def sync_symbol(
        self,
        symbol_config: SymbolConfig,
        timeframe: Timeframe,
        progress_callback: Optional[Callable[[SyncProgress], None]] = None,
    ) -> dict:
        bars_fetched = 0
        ranges_processed = 0
        errors = []
        tf_name = timeframe.name if isinstance(timeframe, Timeframe) else str(timeframe)

        try:
            contract = self._client.make_contract(symbol_config)
        except Exception as e:
            return {
                "symbol": symbol_config.symbol,
                "timeframe": tf_name,
                "bars_fetched": 0,
                "ranges_processed": 0,
                "errors": [str(e)],
            }

        try:
            ranges = self._prober.get_pending_ranges(symbol_config, timeframe)
        except Exception as e:
            return {
                "symbol": symbol_config.symbol,
                "timeframe": tf_name,
                "bars_fetched": 0,
                "ranges_processed": 0,
                "errors": [str(e)],
            }

        if not ranges:
            return {
                "symbol": symbol_config.symbol,
                "timeframe": tf_name,
                "bars_fetched": 0,
                "ranges_processed": 0,
                "errors": [],
            }

        for tr in ranges:
            try:
                self._rate_limiter.acquire("hist", symbol_config.symbol)
                bars = self._client.get_historical_bars(
                    contract=contract,
                    timeframe=timeframe,
                    end_date_time=tr.end.strftime("%Y%m%d-%H:%M:%S"),
                    duration=self._duration_str(tr.end - tr.start),
                    what_to_show=symbol_config.what_to_show,
                )

                for b in bars:
                    self._db.write_kline(b)
                    bars_fetched += 1

                if bars:
                    latest_bar = bars[-1]
                    self._db.update_sync_status(SyncStatus(
                        symbol=symbol_config.symbol,
                        timeframe=tf_name,
                        latest_bar_time=latest_bar.timestamp,
                        bar_count=len(bars),
                        synced_at=datetime.now(timezone.utc),
                    ))

                ranges_processed += 1

                if progress_callback:
                    progress_callback(SyncProgress(
                        symbol=symbol_config.symbol,
                        timeframe=tf_name,
                        phase="fetching",
                        current_range=ranges_processed,
                        total_ranges=len(ranges),
                        bars_fetched=len(bars),
                        elapsed_sec=0.0,
                        eta_sec=None,
                    ))

            except Exception as e:
                errors.append(str(e))

        return {
            "symbol": symbol_config.symbol,
            "timeframe": tf_name,
            "bars_fetched": bars_fetched,
            "ranges_processed": ranges_processed,
            "errors": errors,
        }

    def sync_all(
        self,
        symbols: list[SymbolConfig],
        timeframes: Optional[list[Timeframe]] = None,
        progress_callback: Optional[Callable[[SyncProgress], None]] = None,
    ) -> dict:
        if timeframes is None:
            timeframes = list(Timeframe)

        total_bars = 0
        symbols_processed = 0
        all_errors = []

        for sym in symbols:
            for tf in timeframes:
                result = self.sync_symbol(sym, tf, progress_callback)
                total_bars += result["bars_fetched"]
                if result["bars_fetched"] > 0 or not result["errors"]:
                    symbols_processed += 1
                all_errors.extend(result["errors"])

        return {
            "total_bars": total_bars,
            "symbols_processed": symbols_processed,
            "errors": all_errors,
        }

    def _duration_str(self, delta) -> str:
        seconds = int(delta.total_seconds())
        if seconds >= 86400:
            days = seconds // 86400
            return f"{days} D"
        elif seconds >= 3600:
            hours = seconds // 3600
            return f"{hours} H"
        elif seconds >= 60:
            mins = seconds // 60
            return f"{mins} M"
        else:
            return f"{seconds} S"
