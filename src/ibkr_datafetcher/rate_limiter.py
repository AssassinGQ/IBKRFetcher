import threading
import time
from dataclasses import dataclass
from enum import Enum
from typing import Optional


class RequestType(Enum):
    HISTORICAL = "historical"
    NEWS = "news"


@dataclass
class RateLimitConfig:
    hist_per_min: int = 6
    news_per_min: int = 3
    dedup_window_sec: int = 15
    symbol_per_sec: int = 3


class RateLimiter:
    def __init__(self, config: Optional[RateLimitConfig] = None):
        self.config = config or RateLimitConfig()
        self._lock = threading.Lock()
        self._hist_timestamps: list[float] = []
        self._news_timestamps: list[float] = []
        self._dedup_cache: dict[str, float] = {}
        self._symbol_timestamps: dict[str, list[float]] = {}
        self._total_requests = 0
        self._rejected_requests = 0
        self._total_wait_time = 0.0

    def _clean_old_timestamps(self, timestamps: list[float], window_sec: int) -> None:
        cutoff = time.time() - window_sec
        while timestamps and timestamps[0] < cutoff:
            timestamps.pop(0)

    def _get_request_key(self, request_type: RequestType, symbol: str, 
                         timeframe: Optional[str] = None) -> str:
        parts = [request_type.value, symbol]
        if timeframe:
            parts.append(timeframe)
        return "|".join(parts)

    def _check_can_request(self, request_type: RequestType, symbol: str,
                           timeframe: Optional[str] = None) -> bool:
        self._clean_old_timestamps(self._hist_timestamps, 60)
        self._clean_old_timestamps(self._news_timestamps, 60)

        key = self._get_request_key(request_type, symbol, timeframe)
        dedup_cutoff = time.time() - self.config.dedup_window_sec
        if key in self._dedup_cache and self._dedup_cache[key] > dedup_cutoff:
            return False

        timestamps = (self._hist_timestamps if request_type == RequestType.HISTORICAL
                      else self._news_timestamps)
        limit = (self.config.hist_per_min if request_type == RequestType.HISTORICAL
                 else self.config.news_per_min)

        if len(timestamps) >= limit:
            return False

        symbol_timestamps = self._symbol_timestamps.get(symbol, [])
        self._clean_old_timestamps(symbol_timestamps, 1)
        if len(symbol_timestamps) >= self.config.symbol_per_sec:
            return False

        return True

    def can_request(self, request_type: RequestType, symbol: str,
                    timeframe: Optional[str] = None) -> bool:
        with self._lock:
            return self._check_can_request(request_type, symbol, timeframe)

    def request(self, request_type: RequestType, symbol: str,
                timeframe: Optional[str] = None) -> bool:
        with self._lock:
            if not self._check_can_request(request_type, symbol, timeframe):
                self._rejected_requests += 1
                return False

            now = time.time()
            timestamps = (self._hist_timestamps if request_type == RequestType.HISTORICAL
                          else self._news_timestamps)
            timestamps.append(now)

            key = self._get_request_key(request_type, symbol, timeframe)
            self._dedup_cache[key] = now

            if symbol not in self._symbol_timestamps:
                self._symbol_timestamps[symbol] = []
            self._symbol_timestamps[symbol].append(now)

            self._total_requests += 1
            return True

    def wait_and_request(self, request_type: RequestType, symbol: str,
                         timeframe: Optional[str] = None,
                         timeout: float = 30.0) -> bool:
        start_time = time.time()
        while time.time() - start_time < timeout:
            if self.request(request_type, symbol, timeframe):
                return True
            sleep_time = 0.1 + (time.time() - start_time) / timeout * 0.5
            time.sleep(min(sleep_time, 1.0))
        return False

    def get_load_factor(self, request_type: RequestType) -> float:
        with self._lock:
            self._clean_old_timestamps(self._hist_timestamps, 60)
            self._clean_old_timestamps(self._news_timestamps, 60)
            
            timestamps = (self._hist_timestamps if request_type == RequestType.HISTORICAL 
                          else self._news_timestamps)
            limit = (self.config.hist_per_min if request_type == RequestType.HISTORICAL 
                     else self.config.news_per_min)
            
            return len(timestamps) / limit if limit > 0 else 0.0

    def get_stats(self) -> dict:
        with self._lock:
            self._clean_old_timestamps(self._hist_timestamps, 60)
            self._clean_old_timestamps(self._news_timestamps, 60)
            
            return {
                "hist_in_flight": len(self._hist_timestamps),
                "hist_limit": self.config.hist_per_min,
                "hist_load": len(self._hist_timestamps) / self.config.hist_per_min,
                "news_in_flight": len(self._news_timestamps),
                "news_limit": self.config.news_per_min,
                "news_load": len(self._news_timestamps) / self.config.news_per_min,
                "dedup_entries": len(self._dedup_cache),
                "total_requests": self._total_requests,
                "rejected_requests": self._rejected_requests,
                "avg_wait_time": (self._total_wait_time / self._total_requests 
                                  if self._total_requests > 0 else 0.0),
            }

    def reset(self) -> None:
        with self._lock:
            self._hist_timestamps.clear()
            self._news_timestamps.clear()
            self._dedup_cache.clear()
            self._symbol_timestamps.clear()
            self._total_requests = 0
            self._rejected_requests = 0
            self._total_wait_time = 0.0
