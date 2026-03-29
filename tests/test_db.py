"""UC-P2-1 through UC-P2-27: Database worker, WAL, CRUD, and queries."""

import sqlite3
import time
from datetime import datetime

import pytest

from ibkr_datafetcher.db import Database
from ibkr_datafetcher.types import KlineBar, NewsItem, SyncStatus, Timeframe


def _bar(
    symbol: str,
    tf: Timeframe,
    ts: int,
    bt: datetime | None = None,
) -> KlineBar:
    if bt is None:
        bt = datetime.fromtimestamp(ts)
    return KlineBar(
        symbol=symbol,
        timeframe=tf,
        timestamp=ts,
        open=1.0,
        high=2.0,
        low=0.5,
        close=1.5,
        volume=100.0,
        bar_count=1,
        bar_time=bt,
    )


def test_uc_p2_1_database_creates_tables_and_worker_alive(tmp_path):
    path = str(tmp_path / "t.db")
    db = Database(path)
    try:
        assert db._worker.is_alive()
        raw = sqlite3.connect(path)
        try:
            rows = raw.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            ).fetchall()
            names = {r[0] for r in rows}
            assert names == {"earliest_times", "kline_bars", "news", "sync_status"}
        finally:
            raw.close()
    finally:
        db.close()


def test_uc_p2_2_wal_mode_active(tmp_path):
    path = str(tmp_path / "t.db")
    db = Database(path)
    try:
        raw = sqlite3.connect(path)
        try:
            mode = raw.execute("PRAGMA journal_mode").fetchone()[0].lower()
            assert mode == "wal"
        finally:
            raw.close()
    finally:
        db.close()


def test_uc_p2_3_close_stops_thread(tmp_path):
    path = str(tmp_path / "t.db")
    db = Database(path)
    db.close()
    assert not db._worker.is_alive()


def test_uc_p2_4_insert_ten_klines_query_finds(tmp_path):
    path = str(tmp_path / "t.db")
    db = Database(path)
    try:
        bars = [_bar("AAPL", Timeframe.M1, 1000 + i) for i in range(10)]
        db.insert_kline_bars(bars)
        time.sleep(0.1)
        out = db.query_klines("AAPL", Timeframe.M1.name)
        assert len(out) == 10
        assert {b.timestamp for b in out} == {1000 + i for i in range(10)}
    finally:
        db.close()


def test_uc_p2_5_insert_1000_bars_returns_quickly(tmp_path):
    path = str(tmp_path / "t.db")
    db = Database(path)
    try:
        bars = [_bar("AAPL", Timeframe.M1, 2000 + i) for i in range(1000)]
        t0 = time.perf_counter()
        db.insert_kline_bars(bars)
        elapsed = time.perf_counter() - t0
        assert elapsed < 0.01
        time.sleep(0.2)
        assert len(db.query_klines("AAPL", Timeframe.M1.name)) == 1000
    finally:
        db.close()


def test_uc_p2_6_duplicate_insert_upserts(tmp_path):
    path = str(tmp_path / "t.db")
    db = Database(path)
    try:
        bt = datetime(2024, 1, 1, 12, 0, 0)
        b1 = KlineBar(
            symbol="AAPL",
            timeframe=Timeframe.M5,
            timestamp=5000,
            open=1.0,
            high=2.0,
            low=0.5,
            close=1.5,
            volume=10.0,
            bar_count=1,
            bar_time=bt,
        )
        b2 = KlineBar(
            symbol="AAPL",
            timeframe=Timeframe.M5,
            timestamp=5000,
            open=9.0,
            high=9.0,
            low=9.0,
            close=9.0,
            volume=99.0,
            bar_count=2,
            bar_time=bt,
        )
        db.insert_kline_bars([b1])
        time.sleep(0.1)
        db.insert_kline_bars([b2])
        time.sleep(0.1)
        rows = db.query_klines("AAPL", Timeframe.M5.name)
        assert len(rows) == 1
        assert rows[0].close == 9.0
        assert rows[0].bar_count == 2
    finally:
        db.close()


def test_uc_p2_7_update_sync_get_all_includes(tmp_path):
    path = str(tmp_path / "t.db")
    db = Database(path)
    try:
        st = SyncStatus(
            symbol="MSFT",
            timeframe=Timeframe.H1,
            latest_bar_time=777,
            bar_count=3,
            synced_at=datetime(2024, 6, 1, 10, 0, 0),
        )
        db.update_sync_status(st)
        time.sleep(0.1)
        all_s = db.get_all_sync_status()
        assert len(all_s) == 1
        assert all_s[0].symbol == "MSFT"
        assert all_s[0].latest_bar_time == 777
    finally:
        db.close()


def test_uc_p2_8_double_update_same_key_latest_value(tmp_path):
    path = str(tmp_path / "t.db")
    db = Database(path)
    try:
        s1 = SyncStatus(
            symbol="AAPL",
            timeframe=Timeframe.M1,
            latest_bar_time=1,
            bar_count=1,
            synced_at=datetime(2024, 1, 1, 0, 0, 0),
        )
        s2 = SyncStatus(
            symbol="AAPL",
            timeframe=Timeframe.M1,
            latest_bar_time=99,
            bar_count=50,
            synced_at=datetime(2024, 2, 1, 0, 0, 0),
        )
        db.update_sync_status(s1)
        time.sleep(0.05)
        db.update_sync_status(s2)
        time.sleep(0.1)
        rows = db.get_all_sync_status()
        assert len(rows) == 1
        assert rows[0].latest_bar_time == 99
        assert rows[0].bar_count == 50
    finally:
        db.close()


def test_uc_p2_9_get_sync_status_symbol_filter(tmp_path):
    path = str(tmp_path / "t.db")
    db = Database(path)
    try:
        db.update_sync_status(
            SyncStatus(
                "AAPL",
                Timeframe.M1,
                1,
                1,
                datetime(2024, 1, 1),
            )
        )
        db.update_sync_status(
            SyncStatus(
                "GOOG",
                Timeframe.M1,
                2,
                2,
                datetime(2024, 1, 2),
            )
        )
        time.sleep(0.1)
        aapl = db.get_sync_status("AAPL")
        assert len(aapl) == 1
        assert aapl[0].symbol == "AAPL"
    finally:
        db.close()


def test_uc_p2_10_get_all_sync_status_returns_all(tmp_path):
    path = str(tmp_path / "t.db")
    db = Database(path)
    try:
        db.update_sync_status(
            SyncStatus("X", Timeframe.M1, 1, 1, datetime(2024, 1, 1))
        )
        db.update_sync_status(
            SyncStatus("Y", Timeframe.M5, 2, 2, datetime(2024, 1, 2))
        )
        time.sleep(0.1)
        all_s = db.get_all_sync_status()
        syms = {s.symbol for s in all_s}
        assert syms == {"X", "Y"}
    finally:
        db.close()


def test_uc_p2_11_get_latest_bar_time_empty_none(tmp_path):
    path = str(tmp_path / "t.db")
    db = Database(path)
    try:
        assert db.get_latest_bar_time("AAPL", Timeframe.M1.name) is None
    finally:
        db.close()


def test_uc_p2_12_get_latest_bar_time_after_inserts_max_ts(tmp_path):
    path = str(tmp_path / "t.db")
    db = Database(path)
    try:
        db.insert_kline_bars(
            [
                _bar("AAPL", Timeframe.M1, 100),
                _bar("AAPL", Timeframe.M1, 500),
                _bar("AAPL", Timeframe.M1, 300),
            ]
        )
        time.sleep(0.1)
        assert db.get_latest_bar_time("AAPL", Timeframe.M1.name) == 500
    finally:
        db.close()


def test_uc_p2_13_different_timeframes_no_interference(tmp_path):
    path = str(tmp_path / "t.db")
    db = Database(path)
    try:
        db.insert_kline_bars([_bar("AAPL", Timeframe.M1, 1000)])
        db.insert_kline_bars([_bar("AAPL", Timeframe.M5, 9999)])
        time.sleep(0.1)
        assert db.get_latest_bar_time("AAPL", Timeframe.M1.name) == 1000
        assert db.get_latest_bar_time("AAPL", Timeframe.M5.name) == 9999
    finally:
        db.close()


def test_uc_p2_14_set_earliest_get_same(tmp_path):
    path = str(tmp_path / "t.db")
    db = Database(path)
    try:
        db.set_earliest_time("AAPL", Timeframe.D1.name, 42)
        time.sleep(0.1)
        assert db.get_earliest_time("AAPL", Timeframe.D1.name) == 42
    finally:
        db.close()


def test_uc_p2_15_get_earliest_unset_none(tmp_path):
    path = str(tmp_path / "t.db")
    db = Database(path)
    try:
        assert db.get_earliest_time("ZZZ", Timeframe.M1.name) is None
    finally:
        db.close()


def test_uc_p2_16_double_set_earliest_overwritten(tmp_path):
    path = str(tmp_path / "t.db")
    db = Database(path)
    try:
        db.set_earliest_time("AAPL", Timeframe.M1.name, 1)
        time.sleep(0.05)
        db.set_earliest_time("AAPL", Timeframe.M1.name, 2)
        time.sleep(0.1)
        assert db.get_earliest_time("AAPL", Timeframe.M1.name) == 2
    finally:
        db.close()


def test_uc_p2_17_query_klines_symbol_timeframe_filter(tmp_path):
    path = str(tmp_path / "t.db")
    db = Database(path)
    try:
        db.insert_kline_bars([_bar("AAPL", Timeframe.M1, 1)])
        db.insert_kline_bars([_bar("MSFT", Timeframe.M1, 2)])
        time.sleep(0.1)
        a = db.query_klines("AAPL", Timeframe.M1.name)
        assert len(a) == 1 and a[0].symbol == "AAPL"
    finally:
        db.close()


def test_uc_p2_18_query_klines_from_to_range(tmp_path):
    path = str(tmp_path / "t.db")
    db = Database(path)
    try:
        db.insert_kline_bars([_bar("AAPL", Timeframe.M1, 10 + i) for i in range(10)])
        time.sleep(0.1)
        rows = db.query_klines("AAPL", Timeframe.M1.name, from_time=12, to_time=16)
        ts = [r.timestamp for r in rows]
        assert ts == [12, 13, 14, 15, 16]
    finally:
        db.close()


def test_uc_p2_19_query_klines_limit(tmp_path):
    path = str(tmp_path / "t.db")
    db = Database(path)
    try:
        db.insert_kline_bars([_bar("AAPL", Timeframe.M1, i) for i in range(20)])
        time.sleep(0.1)
        rows = db.query_klines("AAPL", Timeframe.M1.name, limit=3)
        assert len(rows) == 3
    finally:
        db.close()


def test_uc_p2_20_query_klines_sorted_asc(tmp_path):
    path = str(tmp_path / "t.db")
    db = Database(path)
    try:
        db.insert_kline_bars(
            [
                _bar("AAPL", Timeframe.M1, 300),
                _bar("AAPL", Timeframe.M1, 100),
                _bar("AAPL", Timeframe.M1, 200),
            ]
        )
        time.sleep(0.1)
        ts = [b.timestamp for b in db.query_klines("AAPL", Timeframe.M1.name)]
        assert ts == [100, 200, 300]
    finally:
        db.close()


def test_uc_p2_21_query_klines_no_match_empty(tmp_path):
    path = str(tmp_path / "t.db")
    db = Database(path)
    try:
        db.insert_kline_bars([_bar("AAPL", Timeframe.M1, 1)])
        time.sleep(0.1)
        assert db.query_klines("NONE", Timeframe.M1.name) == []
    finally:
        db.close()


def test_uc_p2_22_get_latest_news_time_empty_none(tmp_path):
    path = str(tmp_path / "t.db")
    db = Database(path)
    try:
        assert db.get_latest_news_time("AAPL") is None
    finally:
        db.close()


def test_uc_p2_23_get_latest_news_time_after_insert_max(tmp_path):
    path = str(tmp_path / "t.db")
    db = Database(path)
    try:
        items = [
            NewsItem("a1", "AAPL", "h1", "P", 100),
            NewsItem("a2", "AAPL", "h2", "P", 500),
            NewsItem("a3", "AAPL", "h3", "P", 300),
        ]
        db.insert_news(items)
        time.sleep(0.1)
        assert db.get_latest_news_time("AAPL") == 500
    finally:
        db.close()


def test_uc_p2_24_news_different_symbols_isolated(tmp_path):
    path = str(tmp_path / "t.db")
    db = Database(path)
    try:
        db.insert_news([NewsItem("n1", "AAPL", "h", "P", 1000)])
        db.insert_news([NewsItem("n2", "MSFT", "h", "P", 2000)])
        time.sleep(0.1)
        assert db.get_latest_news_time("AAPL") == 1000
        assert db.get_latest_news_time("MSFT") == 2000
    finally:
        db.close()


def test_uc_p2_25_insert_news_query_finds(tmp_path):
    path = str(tmp_path / "t.db")
    db = Database(path)
    try:
        db.insert_news(
            [
                NewsItem("x1", "AAPL", "one", "R", 1),
                NewsItem("x2", "AAPL", "two", "R", 2),
            ]
        )
        time.sleep(0.1)
        rows = db.query_news()
        assert len(rows) == 2
        ids = {r.article_id for r in rows}
        assert ids == {"x1", "x2"}
    finally:
        db.close()


def test_uc_p2_26_query_news_symbol_filter(tmp_path):
    path = str(tmp_path / "t.db")
    db = Database(path)
    try:
        db.insert_news([NewsItem("a", "AAPL", "h", "P", 1)])
        db.insert_news([NewsItem("b", "MSFT", "h", "P", 2)])
        time.sleep(0.1)
        rows = db.query_news(symbol="AAPL")
        assert len(rows) == 1
        assert rows[0].article_id == "a"
    finally:
        db.close()


def test_uc_p2_27_duplicate_article_id_upserts(tmp_path):
    path = str(tmp_path / "t.db")
    db = Database(path)
    try:
        n1 = NewsItem("same", "AAPL", "old", "P", 1)
        n2 = NewsItem("same", "AAPL", "newhead", "P", 2)
        db.insert_news([n1])
        time.sleep(0.05)
        db.insert_news([n2])
        time.sleep(0.1)
        rows = db.query_news()
        assert len(rows) == 1
        assert rows[0].headline == "newhead"
        assert rows[0].timestamp == 2
    finally:
        db.close()
