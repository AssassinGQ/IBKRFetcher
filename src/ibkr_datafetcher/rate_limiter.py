from __future__ import annotations

import threading
import time
from collections import deque


class RateLimiter:
    def __init__(
        self,
        hist_requests_per_minute: int = 6,
        news_requests_per_minute: int = 3,
        identical_cooldown: float = 15.0,
        same_contract_limit: int = 6,
        same_contract_window: float = 2.0,
    ) -> None:
        self._hist_rpm = hist_requests_per_minute
        self._news_rpm = news_requests_per_minute
        self._identical_cooldown = identical_cooldown
        self._same_contract_limit = same_contract_limit
        self._same_contract_window = same_contract_window

        self._lock = threading.Lock()
        self._hist_ts: deque[float] = deque()
        self._news_ts: deque[float] = deque()
        self._last_identical: dict[tuple[str, str, str], float] = {}
        self._contract_ts: dict[str, deque[float]] = {}

        self._hist_requests = 0
        self._news_requests = 0
        self._total_waits = 0
        self._total_wait_time = 0.0

    def acquire(
        self,
        request_type: str = "hist",
        symbol: str = "",
        exchange: str = "",
        sec_type: str = "STK",
    ) -> None:
        bucket = "news" if request_type == "news" else "hist"
        rpm = self._news_rpm if bucket == "news" else self._hist_rpm
        dq_global = self._news_ts if bucket == "news" else self._hist_ts
        key = (symbol, exchange, sec_type)

        while True:
            wait = 0.0
            with self._lock:
                now = time.monotonic()
                self._prune_minute(dq_global, now)
                wait = self._wait_for_global(dq_global, rpm, now)
                if symbol:
                    last = self._last_identical.get(key)
                    if last is not None:
                        elapsed = now - last
                        if elapsed < self._identical_cooldown:
                            need = self._identical_cooldown - elapsed
                            wait = max(wait, need)

                    cdq = self._contract_ts.setdefault(symbol, deque())
                    self._prune_window(cdq, now, self._same_contract_window)
                    if len(cdq) >= self._same_contract_limit:
                        oldest = cdq[0]
                        need = oldest + self._same_contract_window - now
                        wait = max(wait, need)

                if wait <= 0:
                    self._grant(bucket, dq_global, symbol, key, now)
                    return

            slept = wait
            with self._lock:
                self._total_waits += 1
            t0 = time.monotonic()
            time.sleep(slept)
            with self._lock:
                self._total_wait_time += time.monotonic() - t0

    def get_stats(self) -> dict:
        with self._lock:
            now = time.monotonic()
            self._prune_minute(self._hist_ts, now)
            self._prune_minute(self._news_ts, now)
            hist_n = len(self._hist_ts)
            news_n = len(self._news_ts)
            util_hist = hist_n / self._hist_rpm if self._hist_rpm else 0.0
            util_news = news_n / self._news_rpm if self._news_rpm else 0.0
            utilization = max(util_hist, util_news)
            tw = self._total_waits
            avg = self._total_wait_time / tw if tw else 0.0
            return {
                "hist_requests": self._hist_requests,
                "news_requests": self._news_requests,
                "total_waits": self._total_waits,
                "avg_wait_time": avg,
                "utilization": utilization,
            }

    def _prune_minute(self, dq: deque[float], now: float) -> None:
        cutoff = now - 60.0
        while dq and dq[0] <= cutoff:
            dq.popleft()

    def _prune_window(self, dq: deque[float], now: float, window: float) -> None:
        cutoff = now - window
        while dq and dq[0] <= cutoff:
            dq.popleft()

    def _wait_for_global(self, dq: deque[float], rpm: int, now: float) -> float:
        if len(dq) < rpm:
            return 0.0
        oldest = dq[0]
        return oldest + 60.0 - now

    def _grant(
        self,
        bucket: str,
        dq_global: deque[float],
        symbol: str,
        key: tuple[str, str, str],
        now: float,
    ) -> None:
        dq_global.append(now)
        if bucket == "hist":
            self._hist_requests += 1
        else:
            self._news_requests += 1
        if symbol:
            self._last_identical[key] = now
            cdq = self._contract_ts.setdefault(symbol, deque())
            self._prune_window(cdq, now, self._same_contract_window)
            cdq.append(now)
