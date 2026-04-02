from __future__ import annotations

import sqlite3
import threading
from collections.abc import Callable
from datetime import datetime
from queue import Queue
from typing import Any, Optional

from ibkr_datafetcher.types import KlineBar, NewsItem, SyncStatus, Timeframe

_SENTINEL = object()


def _row_to_kline(row: sqlite3.Row) -> KlineBar:
    return KlineBar(
        symbol=row["symbol"],
        timeframe=Timeframe[row["timeframe"]],
        timestamp=row["timestamp"],
        open=row["open"],
        high=row["high"],
        low=row["low"],
        close=row["close"],
        volume=row["volume"],
        bar_count=row["bar_count"],
        bar_time=datetime.fromisoformat(row["bar_time"]),
    )


def _row_to_sync_status(row: sqlite3.Row) -> SyncStatus:
    return SyncStatus(
        symbol=row["symbol"],
        timeframe=Timeframe[row["timeframe"]],
        latest_bar_time=row["latest_bar_time"],
        bar_count=row["bar_count"],
        synced_at=datetime.fromisoformat(row["synced_at"]),
    )


def _row_to_news(row: sqlite3.Row) -> NewsItem:
    return NewsItem(
        article_id=row["article_id"],
        symbol=row["symbol"],
        headline=row["headline"],
        provider_code=row["provider_code"],
        timestamp=row["timestamp"],
    )


class Database:
    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._queue: Queue[Any] = Queue()
        self._ready = threading.Event()
        self._worker = threading.Thread(target=self._db_worker, name="db_worker", daemon=True)
        self._worker.start()
        if not self._ready.wait(timeout=30):
            msg = "database worker failed to initialize"
            raise RuntimeError(msg)

    def _db_worker(self) -> None:
        conn = sqlite3.connect(self._db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS kline_bars (
                symbol TEXT NOT NULL,
                timeframe TEXT NOT NULL,
                timestamp INTEGER NOT NULL,
                open REAL NOT NULL,
                high REAL NOT NULL,
                low REAL NOT NULL,
                close REAL NOT NULL,
                volume REAL NOT NULL,
                bar_count INTEGER NOT NULL,
                bar_time TEXT NOT NULL,
                PRIMARY KEY (symbol, timeframe, timestamp)
            );
            CREATE TABLE IF NOT EXISTS sync_status (
                symbol TEXT NOT NULL,
                timeframe TEXT NOT NULL,
                latest_bar_time INTEGER NOT NULL,
                bar_count INTEGER NOT NULL,
                synced_at TEXT NOT NULL,
                PRIMARY KEY (symbol, timeframe)
            );
            CREATE TABLE IF NOT EXISTS earliest_times (
                symbol TEXT NOT NULL,
                timeframe TEXT NOT NULL,
                timestamp INTEGER NOT NULL,
                PRIMARY KEY (symbol, timeframe)
            );
            CREATE TABLE IF NOT EXISTS news (
                article_id TEXT NOT NULL PRIMARY KEY,
                symbol TEXT,
                headline TEXT NOT NULL,
                provider_code TEXT NOT NULL,
                timestamp INTEGER NOT NULL
            );
            """
        )
        conn.commit()
        self._ready.set()
        while True:
            item = self._queue.get()
            if item is _SENTINEL:
                break
            if isinstance(item, tuple) and item[0] == "read":
                _, fn, done, err_box, result_box = item
                try:
                    result_box[0] = fn(conn)
                except (sqlite3.Error, ValueError, TypeError) as e:
                    err_box[0] = e
                finally:
                    done.set()
            else:
                write_fn: Callable[[sqlite3.Connection], None] = item
                write_fn(conn)
                conn.commit()
        conn.close()

    def _enqueue_write(self, fn: Callable[[sqlite3.Connection], None]) -> None:
        self._queue.put(fn)

    def _enqueue_read(self, fn: Callable[[sqlite3.Connection], Any]) -> Any:
        done = threading.Event()
        result_box: list[Any] = [None]
        err_box: list[Optional[BaseException]] = [None]
        self._queue.put(("read", fn, done, err_box, result_box))
        done.wait()
        exc = err_box[0]
        if exc is not None:
            raise exc
        return result_box[0]

    def close(self) -> None:
        self._queue.put(_SENTINEL)
        self._worker.join()

    def insert_kline_bars(self, bars: list[KlineBar]) -> None:
        if not bars:
            return

        def _w(conn: sqlite3.Connection) -> None:
            conn.executemany(
                """INSERT OR REPLACE INTO kline_bars
                (symbol, timeframe, timestamp, open, high, low, close, volume, bar_count, bar_time)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    (
                        b.symbol,
                        b.timeframe.name,
                        b.timestamp,
                        b.open,
                        b.high,
                        b.low,
                        b.close,
                        b.volume,
                        b.bar_count,
                        b.bar_time.isoformat(),
                    )
                    for b in bars
                ],
            )

        self._enqueue_write(_w)

    def update_sync_status(self, status: SyncStatus) -> None:
        def _w(conn: sqlite3.Connection) -> None:
            conn.execute(
                """INSERT OR REPLACE INTO sync_status
                (symbol, timeframe, latest_bar_time, bar_count, synced_at)
                VALUES (?, ?, ?, ?, ?)""",
                (
                    status.symbol,
                    status.timeframe.name,
                    status.latest_bar_time,
                    status.bar_count,
                    status.synced_at.isoformat(),
                ),
            )

        self._enqueue_write(_w)

    def set_earliest_time(self, symbol: str, timeframe: str, timestamp: int) -> None:
        def _w(conn: sqlite3.Connection) -> None:
            conn.execute(
                """INSERT OR REPLACE INTO earliest_times (symbol, timeframe, timestamp)
                VALUES (?, ?, ?)""",
                (symbol, timeframe, timestamp),
            )

        self._enqueue_write(_w)

    def insert_news(self, items: list[NewsItem]) -> None:
        if not items:
            return

        def _w(conn: sqlite3.Connection) -> None:
            conn.executemany(
                """INSERT OR REPLACE INTO news
                (article_id, symbol, headline, provider_code, timestamp)
                VALUES (?, ?, ?, ?, ?)""",
                [
                    (n.article_id, n.symbol, n.headline, n.provider_code, n.timestamp)
                    for n in items
                ],
            )

        self._enqueue_write(_w)

    def get_latest_bar_time(self, symbol: str, timeframe: str) -> Optional[int]:
        def _r(conn: sqlite3.Connection) -> Optional[int]:
            row = conn.execute(
                "SELECT MAX(timestamp) AS m FROM kline_bars WHERE symbol = ? AND timeframe = ?",
                (symbol, timeframe),
            ).fetchone()
            if row is None or row["m"] is None:
                return None
            return int(row["m"])

        return self._enqueue_read(_r)

    def get_earliest_time(self, symbol: str, timeframe: str) -> Optional[int]:
        def _r(conn: sqlite3.Connection) -> Optional[int]:
            row = conn.execute(
                "SELECT timestamp FROM earliest_times WHERE symbol = ? AND timeframe = ?",
                (symbol, timeframe),
            ).fetchone()
            if row is None:
                return None
            return int(row["timestamp"])

        return self._enqueue_read(_r)

    def query_klines(
        self,
        symbol: str,
        timeframe: str,
        from_time: Optional[int] = None,
        to_time: Optional[int] = None,
        limit: Optional[int] = None,
    ) -> list[KlineBar]:
        def _r(conn: sqlite3.Connection) -> list[KlineBar]:
            q = "SELECT * FROM kline_bars WHERE symbol = ? AND timeframe = ?"
            params: list[Any] = [symbol, timeframe]
            if from_time is not None:
                q += " AND timestamp >= ?"
                params.append(from_time)
            if to_time is not None:
                q += " AND timestamp <= ?"
                params.append(to_time)
            q += " ORDER BY timestamp ASC"
            if limit is not None:
                q += " LIMIT ?"
                params.append(limit)
            rows = conn.execute(q, params).fetchall()
            return [_row_to_kline(r) for r in rows]

        return self._enqueue_read(_r)

    def get_time_range(self, symbol: str, timeframe: str) -> tuple[Optional[int], Optional[int]]:
        """返回 (earliest_timestamp, latest_timestamp)"""

        def _r(conn: sqlite3.Connection) -> tuple[Optional[int], Optional[int]]:
            row = conn.execute(
                "SELECT MIN(timestamp) as earliest, MAX(timestamp) as latest "
                "FROM kline_bars WHERE symbol = ? AND timeframe = ?",
                (symbol, timeframe),
            ).fetchone()
            return (row["earliest"], row["latest"])

        return self._enqueue_read(_r)

    def get_timeframes_for_symbol(self, symbol: str) -> list[str]:
        """返回该 symbol 所有已存储的 timeframe 列表"""

        def _r(conn: sqlite3.Connection) -> list[str]:
            rows = conn.execute(
                "SELECT DISTINCT timeframe FROM kline_bars WHERE symbol = ? ORDER BY timeframe",
                (symbol,),
            ).fetchall()
            return [r["timeframe"] for r in rows]

        return self._enqueue_read(_r)

    def get_all_sync_status(self) -> list[SyncStatus]:
        def _r(conn: sqlite3.Connection) -> list[SyncStatus]:
            rows = conn.execute("SELECT * FROM sync_status").fetchall()
            return [_row_to_sync_status(r) for r in rows]

        return self._enqueue_read(_r)

    def get_sync_status(self, symbol: str) -> list[SyncStatus]:
        def _r(conn: sqlite3.Connection) -> list[SyncStatus]:
            rows = conn.execute(
                "SELECT * FROM sync_status WHERE symbol = ? ORDER BY timeframe",
                (symbol,),
            ).fetchall()
            return [_row_to_sync_status(r) for r in rows]

        return self._enqueue_read(_r)

    def get_latest_news_time(self, symbol: str) -> Optional[int]:
        def _r(conn: sqlite3.Connection) -> Optional[int]:
            row = conn.execute(
                "SELECT MAX(timestamp) AS m FROM news WHERE symbol = ?",
                (symbol,),
            ).fetchone()
            if row is None or row["m"] is None:
                return None
            return int(row["m"])

        return self._enqueue_read(_r)

    def query_news(
        self,
        symbol: Optional[str] = None,
        from_time: Optional[int] = None,
        to_time: Optional[int] = None,
        limit: Optional[int] = None,
    ) -> list[NewsItem]:
        def _r(conn: sqlite3.Connection) -> list[NewsItem]:
            q = "SELECT * FROM news WHERE 1=1"
            params: list[Any] = []
            if symbol is not None:
                q += " AND symbol = ?"
                params.append(symbol)
            if from_time is not None:
                q += " AND timestamp >= ?"
                params.append(from_time)
            if to_time is not None:
                q += " AND timestamp <= ?"
                params.append(to_time)
            q += " ORDER BY timestamp ASC"
            if limit is not None:
                q += " LIMIT ?"
                params.append(limit)
            rows = conn.execute(q, params).fetchall()
            return [_row_to_news(r) for r in rows]

        return self._enqueue_read(_r)
