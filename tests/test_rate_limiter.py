import threading
import time

import pytest

from ibkr_datafetcher.rate_limiter import (
    RateLimiter,
    RateLimitConfig,
    RequestType,
)


@pytest.fixture
def limiter():
    return RateLimiter(RateLimitConfig(
        hist_per_min=6,
        news_per_min=3,
        dedup_window_sec=15,
        symbol_per_sec=3,
    ))


class TestRateLimiterInit:
    def test_default_config(self):
        limiter = RateLimiter()
        assert limiter.config.hist_per_min == 6
        assert limiter.config.news_per_min == 3
        assert limiter.config.dedup_window_sec == 15
        assert limiter.config.symbol_per_sec == 3

    def test_custom_config(self):
        limiter = RateLimiter(RateLimitConfig(
            hist_per_min=10,
            news_per_min=5,
            dedup_window_sec=30,
            symbol_per_sec=5,
        ))
        assert limiter.config.hist_per_min == 10
        assert limiter.config.news_per_min == 5


class TestCanRequest:
    def test_historical_request_allowed_initially(self, limiter):
        assert limiter.can_request(RequestType.HISTORICAL, "AAPL", "1 min") is True

    def test_news_request_allowed_initially(self, limiter):
        assert limiter.can_request(RequestType.NEWS, "AAPL") is True

    def test_historical_request_denied_after_limit(self, limiter):
        timeframes = ["1 min", "2 mins", "3 mins", "5 mins", "10 mins", "15 mins"]
        for tf in timeframes:
            limiter.request(RequestType.HISTORICAL, "AAPL", tf)
            time.sleep(0.4)
        
        assert limiter.can_request(RequestType.HISTORICAL, "AAPL", "30 mins") is False

    def test_news_request_denied_after_limit(self, limiter):
        symbols = ["AAPL", "TSLA", "GOOGL"]
        for sym in symbols:
            limiter.request(RequestType.NEWS, sym)
        
        assert limiter.can_request(RequestType.NEWS, "MSFT") is False

    def test_different_symbols_allowed_after_limit(self, limiter):
        timeframes = ["1 min", "2 mins", "3 mins", "5 mins", "10 mins", "15 mins"]
        for tf in timeframes:
            limiter.request(RequestType.HISTORICAL, "AAPL", tf)
        
        assert limiter.can_request(RequestType.HISTORICAL, "TSLA", "1 min") is True

    def test_different_timeframes_allowed(self, limiter):
        timeframes = ["1 min", "2 mins", "3 mins", "5 mins", "10 mins", "15 mins"]
        for tf in timeframes:
            limiter.request(RequestType.HISTORICAL, "AAPL", tf)
        
        assert limiter.can_request(RequestType.HISTORICAL, "AAPL", "30 mins") is False


class TestDedup:
    def test_duplicate_request_denied(self, limiter):
        assert limiter.request(RequestType.HISTORICAL, "AAPL", "1 min") is True
        assert limiter.request(RequestType.HISTORICAL, "AAPL", "1 min") is False

    def test_different_timeframe_not_deduped(self, limiter):
        assert limiter.request(RequestType.HISTORICAL, "AAPL", "1 min") is True
        assert limiter.request(RequestType.HISTORICAL, "AAPL", "5 mins") is True

    def test_different_symbol_not_deduped(self, limiter):
        assert limiter.request(RequestType.HISTORICAL, "AAPL", "1 min") is True
        assert limiter.request(RequestType.HISTORICAL, "TSLA", "1 min") is True


class TestSymbolRateLimit:
    def test_same_symbol_limited_per_second(self, limiter):
        timeframes = ["1 min", "2 mins", "3 mins"]
        for tf in timeframes:
            assert limiter.request(RequestType.HISTORICAL, "AAPL", tf) is True
            time.sleep(0.3)
        
        assert limiter.can_request(RequestType.HISTORICAL, "AAPL", "4 mins") is False

    def test_different_symbols_not_limited_by_same_symbol_rule(self, limiter):
        assert limiter.request(RequestType.HISTORICAL, "AAPL", "1 min") is True
        assert limiter.request(RequestType.HISTORICAL, "TSLA", "1 min") is True


class TestRequest:
    def test_successful_request_increments_counter(self, limiter):
        limiter.request(RequestType.HISTORICAL, "AAPL", "1 min")
        stats = limiter.get_stats()
        assert stats["total_requests"] == 1

    def test_rejected_request_increments_rejected(self, limiter):
        for _ in range(6):
            limiter.request(RequestType.HISTORICAL, "AAPL", "1 min")
        
        limiter.request(RequestType.HISTORICAL, "AAPL", "1 min")
        stats = limiter.get_stats()
        assert stats["rejected_requests"] > 0


class TestWaitAndRequest:
    def test_wait_and_request_blocks_until_allowed(self, limiter):
        limiter.request(RequestType.HISTORICAL, "AAPL", "1 min")
        
        result = limiter.wait_and_request(RequestType.HISTORICAL, "AAPL", "1 min", timeout=0.5)
        assert result is False

    def test_wait_and_request_returns_true_when_allowed(self, limiter):
        result = limiter.wait_and_request(RequestType.HISTORICAL, "AAPL", "1 min", timeout=0.1)
        assert result is True


class TestLoadFactor:
    def test_load_factor_zero_initially(self, limiter):
        assert limiter.get_load_factor(RequestType.HISTORICAL) == 0.0

    def test_load_factor_increases(self, limiter):
        for _ in range(3):
            limiter.request(RequestType.HISTORICAL, "AAPL", "1 min")
        
        load = limiter.get_load_factor(RequestType.HISTORICAL)
        assert 0.0 < load <= 1.0

    def test_load_factor_at_limit(self, limiter):
        timeframes = ["1 min", "2 mins", "3 mins", "5 mins", "10 mins", "15 mins"]
        for tf in timeframes:
            limiter.request(RequestType.HISTORICAL, "AAPL", tf)
            time.sleep(0.4)
        
        load = limiter.get_load_factor(RequestType.HISTORICAL)
        assert load == 1.0


class TestStats:
    def test_stats_contain_required_fields(self, limiter):
        stats = limiter.get_stats()
        assert "hist_in_flight" in stats
        assert "hist_limit" in stats
        assert "hist_load" in stats
        assert "news_in_flight" in stats
        assert "news_limit" in stats
        assert "news_load" in stats
        assert "total_requests" in stats
        assert "rejected_requests" in stats

    def test_reset_clears_stats(self, limiter):
        limiter.request(RequestType.HISTORICAL, "AAPL", "1 min")
        limiter.reset()
        
        stats = limiter.get_stats()
        assert stats["total_requests"] == 0
        assert stats["rejected_requests"] == 0


class TestThreadSafety:
    def test_concurrent_requests_are_safe(self, limiter):
        results = []
        
        def make_requests():
            for _ in range(10):
                if limiter.request(RequestType.HISTORICAL, "AAPL", "1 min"):
                    results.append(True)
                time.sleep(0.05)
        
        threads = [threading.Thread(target=make_requests) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        stats = limiter.get_stats()
        assert stats["total_requests"] == len(results)
