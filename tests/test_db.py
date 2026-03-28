import os
import tempfile
import time
from datetime import datetime

import pytest

from ibkr_datafetcher.db import Database
from ibkr_datafetcher.types import KlineBar, NewsItem, SyncStatus


@pytest.fixture
def db_path():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = f.name
    yield path
    if os.path.exists(path):
        os.unlink(path)
    if os.path.exists(path + "-wal"):
        os.unlink(path + "-wal")
    if os.path.exists(path + "-shm"):
        os.unlink(path + "-shm")


@pytest.fixture
def db(db_path):
    database = Database(db_path)
    database.start()
    yield database
    database.stop()
    time.sleep(0.1)


class TestDatabaseInit:
    def test_init_creates_tables(self, db_path):
        database = Database(db_path)
        assert os.path.exists(db_path)
        database.start()
        time.sleep(0.1)
        database.stop()
        time.sleep(0.1)

        import sqlite3
        c = sqlite3.connect(db_path)
        cursor = c.execute("""
            SELECT name FROM sqlite_master WHERE type='table'
        """)
        tables = {row[0] for row in cursor.fetchall()}
        assert "klines" in tables
        assert "news" in tables
        assert "sync_status" in tables
        c.close()


class TestWriteKline:
    def test_write_single_kline(self, db):
        bar = KlineBar(
            symbol="AAPL",
            timeframe="1 min",
            timestamp=1700000000,
            open=150.0,
            high=151.0,
            low=149.0,
            close=150.5,
            volume=1000000.0,
            bar_count=10,
            bar_time=datetime.fromtimestamp(1700000000),
        )
        db.write_kline(bar)
        time.sleep(0.5)

        result = db.get_latest_bar("AAPL", "1 min")
        assert result is not None
        assert result.symbol == "AAPL"
        assert result.close == 150.5

    def test_write_multiple_klines(self, db):
        for i in range(5):
            bar = KlineBar(
                symbol="AAPL",
                timeframe="5 mins",
                timestamp=1700000000 + i * 300,
                open=150.0 + i,
                high=151.0 + i,
                low=149.0 + i,
                close=150.5 + i,
                volume=1000000.0,
                bar_count=10,
                bar_time=datetime.fromtimestamp(1700000000 + i * 300),
            )
            db.write_kline(bar)
        time.sleep(0.8)

        count = db.get_bar_count("AAPL", "5 mins")
        assert count == 5


class TestWriteNews:
    def test_write_news(self, db):
        news = NewsItem(
            article_id="BRFG$12345",
            symbol="AAPL",
            headline="Apple announces new product",
            provider_code="BRFG",
            timestamp=1700000000,
        )
        db.write_news(news)
        time.sleep(0.5)

        result = db.get_news("AAPL")
        assert len(result) == 1
        assert result[0].article_id == "BRFG$12345"
        assert result[0].headline == "Apple announces new product"


class TestSyncStatus:
    def test_update_and_get_sync_status(self, db):
        bar = KlineBar(
            symbol="AAPL",
            timeframe="1 hour",
            timestamp=1700000000,
            open=150.0,
            high=151.0,
            low=149.0,
            close=150.5,
            volume=1000000.0,
            bar_count=10,
            bar_time=datetime.fromtimestamp(1700000000),
        )
        db.write_kline(bar)

        status = SyncStatus(
            symbol="AAPL",
            timeframe="1 hour",
            latest_bar_time=1700000000,
            bar_count=100,
            synced_at=datetime.now(),
        )
        db.update_sync_status(status)
        time.sleep(0.5)

        result = db.get_sync_status("AAPL", "1 hour")
        assert result is not None
        assert result.symbol == "AAPL"
        assert result.latest_bar_time == 1700000000


class TestGetBars:
    def test_get_bars_in_range(self, db):
        for i in range(10):
            bar = KlineBar(
                symbol="TSLA",
                timeframe="1 min",
                timestamp=1700000000 + i * 60,
                open=200.0 + i,
                high=201.0 + i,
                low=199.0 + i,
                close=200.5 + i,
                volume=500000.0,
                bar_count=5,
                bar_time=datetime.fromtimestamp(1700000000 + i * 60),
            )
            db.write_kline(bar)
        time.sleep(1.0)

        bars = db.get_bars("TSLA", "1 min", 1700000000, 1700000060)
        assert len(bars) == 2


class TestConcurrentWrite:
    def test_concurrent_writes(self, db):
        import threading

        def write_batch(symbol, start_ts):
            for i in range(20):
                bar = KlineBar(
                    symbol=symbol,
                    timeframe="1 min",
                    timestamp=start_ts + i * 60,
                    open=100.0 + i,
                    high=101.0 + i,
                    low=99.0 + i,
                    close=100.5 + i,
                    volume=100000.0,
                    bar_count=1,
                    bar_time=datetime.fromtimestamp(start_ts + i * 60),
                )
                db.write_kline(bar)

        threads = [
            threading.Thread(target=write_batch, args=("AAPL", 1700000000)),
            threading.Thread(target=write_batch, args=("TSLA", 1700002000)),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        time.sleep(1.5)

        assert db.get_bar_count("AAPL", "1 min") == 20
        assert db.get_bar_count("TSLA", "1 min") == 20


class TestReplaceBehavior:
    def test_replace_existing_kline(self, db):
        bar1 = KlineBar(
            symbol="AAPL",
            timeframe="1 min",
            timestamp=1700000000,
            open=150.0,
            high=151.0,
            low=149.0,
            close=150.5,
            volume=1000000.0,
            bar_count=10,
            bar_time=datetime.fromtimestamp(1700000000),
        )
        db.write_kline(bar1)
        time.sleep(0.5)

        bar2 = KlineBar(
            symbol="AAPL",
            timeframe="1 min",
            timestamp=1700000000,
            open=152.0,
            high=153.0,
            low=151.0,
            close=152.5,
            volume=2000000.0,
            bar_count=20,
            bar_time=datetime.fromtimestamp(1700000000),
        )
        db.write_kline(bar2)
        time.sleep(0.5)

        count = db.get_bar_count("AAPL", "1 min")
        assert count == 1

        result = db.get_latest_bar("AAPL", "1 min")
        assert result.close == 152.5
