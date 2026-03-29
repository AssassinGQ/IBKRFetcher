"""UC-P3-1 through UC-P3-16: RateLimiter."""

from __future__ import annotations

import threading
from unittest.mock import patch

import pytest

from ibkr_datafetcher.rate_limiter import RateLimiter


def test_uc_p3_1_default_params_correct():
    rl = RateLimiter()
    assert rl._hist_rpm == 6
    assert rl._news_rpm == 3
    assert rl._identical_cooldown == 15.0
    assert rl._same_contract_limit == 6
    assert rl._same_contract_window == 2.0


def test_uc_p3_2_custom_params_work():
    rl = RateLimiter(
        hist_requests_per_minute=10,
        news_requests_per_minute=5,
        identical_cooldown=1.0,
        same_contract_limit=4,
        same_contract_window=0.5,
    )
    assert rl._hist_rpm == 10
    assert rl._news_rpm == 5
    assert rl._identical_cooldown == 1.0
    assert rl._same_contract_limit == 4
    assert rl._same_contract_window == 0.5


def test_uc_p3_3_six_hist_different_symbols_immediate():
    rl = RateLimiter(hist_requests_per_minute=6)
    for i in range(6):
        rl.acquire("hist", f"S{i}", "SMART", "STK")
    st = rl.get_stats()
    assert st["hist_requests"] == 6
    assert st["total_waits"] == 0


def test_uc_p3_4_seventh_hist_blocks_until_slot():
    mono = {"t": 0.0}

    def fake_monotonic() -> float:
        return mono["t"]

    def fake_sleep(d: float) -> None:
        mono["t"] += d

    rl = RateLimiter(hist_requests_per_minute=6)
    with (
        patch("ibkr_datafetcher.rate_limiter.time.monotonic", fake_monotonic),
        patch("ibkr_datafetcher.rate_limiter.time.sleep", fake_sleep),
    ):
        for i in range(6):
            rl.acquire("hist", f"A{i}", "SMART", "STK")
        rl.acquire("hist", "AZ", "SMART", "STK")
    assert mono["t"] == pytest.approx(60.0)
    assert rl.get_stats()["hist_requests"] == 7


def test_uc_p3_5_identical_within_cooldown_blocks():
    mono = {"t": 0.0}

    def fake_monotonic() -> float:
        return mono["t"]

    def fake_sleep(d: float) -> None:
        mono["t"] += d

    rl = RateLimiter(
        hist_requests_per_minute=100,
        identical_cooldown=0.5,
    )
    with (
        patch("ibkr_datafetcher.rate_limiter.time.monotonic", fake_monotonic),
        patch("ibkr_datafetcher.rate_limiter.time.sleep", fake_sleep),
    ):
        rl.acquire("hist", "IBM", "SMART", "STK")
        rl.acquire("hist", "IBM", "SMART", "STK")
    assert mono["t"] == pytest.approx(0.5)
    assert rl.get_stats()["total_waits"] == 1


def test_uc_p3_6_after_cooldown_identical_passes():
    mono = {"t": 0.0}

    def fake_monotonic() -> float:
        return mono["t"]

    def fake_sleep(d: float) -> None:
        mono["t"] += d

    rl = RateLimiter(
        hist_requests_per_minute=100,
        identical_cooldown=0.4,
    )
    with (
        patch("ibkr_datafetcher.rate_limiter.time.monotonic", fake_monotonic),
        patch("ibkr_datafetcher.rate_limiter.time.sleep", fake_sleep),
    ):
        rl.acquire("hist", "IBM", "SMART", "STK")
        mono["t"] = 0.4
        rl.acquire("hist", "IBM", "SMART", "STK")
    assert rl.get_stats()["total_waits"] == 0
    assert rl.get_stats()["hist_requests"] == 2


def test_uc_p3_7_same_contract_six_in_window_seventh_waits():
    mono = {"t": 0.0}

    def fake_monotonic() -> float:
        return mono["t"]

    def fake_sleep(d: float) -> None:
        mono["t"] += d

    rl = RateLimiter(
        hist_requests_per_minute=100,
        identical_cooldown=0.0,
        same_contract_limit=6,
        same_contract_window=2.0,
    )
    with (
        patch("ibkr_datafetcher.rate_limiter.time.monotonic", fake_monotonic),
        patch("ibkr_datafetcher.rate_limiter.time.sleep", fake_sleep),
    ):
        for _ in range(6):
            rl.acquire("hist", "ONE", "SMART", "STK")
        rl.acquire("hist", "ONE", "SMART", "STK")
    assert mono["t"] == pytest.approx(2.0)
    assert rl.get_stats()["hist_requests"] == 7


def test_uc_p3_8_three_threads_total_count():
    rl = RateLimiter(hist_requests_per_minute=500)
    barrier = threading.Barrier(3)
    errors: list[BaseException] = []

    def worker(wid: int) -> None:
        try:
            barrier.wait()
            for j in range(10):
                rl.acquire("hist", f"W{wid}_{j}", "SMART", "STK")
        except BaseException as e:
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(3)]

    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    assert rl.get_stats()["hist_requests"] == 30


def test_uc_p3_9_empty_symbol_skips_cooldown_and_contract():
    rl = RateLimiter(hist_requests_per_minute=100, identical_cooldown=10.0, same_contract_limit=1)
    for _ in range(20):
        rl.acquire("hist", "", "", "STK")
    st = rl.get_stats()
    assert st["hist_requests"] == 20
    assert st["total_waits"] == 0


def test_uc_p3_10_three_news_immediate():
    rl = RateLimiter(news_requests_per_minute=3)
    for i in range(3):
        rl.acquire("news", f"N{i}", "SMART", "STK")
    st = rl.get_stats()
    assert st["news_requests"] == 3
    assert st["total_waits"] == 0


def test_uc_p3_11_fourth_news_blocks():
    mono = {"t": 0.0}

    def fake_monotonic() -> float:
        return mono["t"]

    def fake_sleep(d: float) -> None:
        mono["t"] += d

    rl = RateLimiter(news_requests_per_minute=3)
    with (
        patch("ibkr_datafetcher.rate_limiter.time.monotonic", fake_monotonic),
        patch("ibkr_datafetcher.rate_limiter.time.sleep", fake_sleep),
    ):
        for i in range(3):
            rl.acquire("news", f"N{i}", "SMART", "STK")
        rl.acquire("news", "N3", "SMART", "STK")
    assert mono["t"] == pytest.approx(60.0)
    assert rl.get_stats()["news_requests"] == 4


def test_uc_p3_12_hist_and_news_independent():
    rl = RateLimiter(hist_requests_per_minute=2, news_requests_per_minute=3)
    rl.acquire("hist", "H0", "SMART", "STK")
    rl.acquire("hist", "H1", "SMART", "STK")
    for i in range(3):
        rl.acquire("news", f"N{i}", "SMART", "STK")
    st = rl.get_stats()
    assert st["news_requests"] == 3
    assert st["hist_requests"] == 2
    assert st["total_waits"] == 0


def test_uc_p3_13_initial_stats_zero():
    rl = RateLimiter()
    st = rl.get_stats()
    assert st["hist_requests"] == 0
    assert st["news_requests"] == 0
    assert st["total_waits"] == 0
    assert st["avg_wait_time"] == 0.0
    assert st["utilization"] == 0.0


def test_uc_p3_14_after_acquires_counts_correct():
    rl = RateLimiter(hist_requests_per_minute=50, news_requests_per_minute=50)
    rl.acquire("hist", "A", "SMART", "STK")
    rl.acquire("hist", "B", "SMART", "STK")
    rl.acquire("news", "C", "SMART", "STK")
    st = rl.get_stats()
    assert st["hist_requests"] == 2
    assert st["news_requests"] == 1


def test_uc_p3_15_after_waits_total_waits_positive():
    mono = {"t": 0.0}

    def fake_monotonic() -> float:
        return mono["t"]

    def fake_sleep(d: float) -> None:
        mono["t"] += d

    rl = RateLimiter(hist_requests_per_minute=1)
    with (
        patch("ibkr_datafetcher.rate_limiter.time.monotonic", fake_monotonic),
        patch("ibkr_datafetcher.rate_limiter.time.sleep", fake_sleep),
    ):
        rl.acquire("hist", "", "", "STK")
        rl.acquire("hist", "", "", "STK")
    assert rl.get_stats()["total_waits"] > 0


def test_uc_p3_16_high_frequency_utilization_near_one():
    rl = RateLimiter(hist_requests_per_minute=10)
    for i in range(10):
        rl.acquire("hist", f"U{i}", "SMART", "STK")
    util = rl.get_stats()["utilization"]
    assert util == pytest.approx(1.0)
