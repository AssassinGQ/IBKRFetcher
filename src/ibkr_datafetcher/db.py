import queue
import sqlite3
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from .types import KlineBar, NewsItem, SyncStatus


@dataclass
class WriteRequest:
    type: str
    data: dict


@dataclass
class ReadRequest:
    id: str
    type: str
    params: dict


class Database:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._write_queue: queue.Queue[WriteRequest] = queue.Queue()
        self._read_response_queues: dict[str, queue.Queue] = {}
        self._read_request_queue: queue.Queue[ReadRequest] = queue.Queue()
        self._worker_thread: Optional[threading.Thread] = None
        self._running = False
        self._lock = threading.Lock()
        self._init_db()

    def _init_db(self) -> None:
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS klines (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
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
                UNIQUE(symbol, timeframe, timestamp)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS news (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                article_id TEXT NOT NULL UNIQUE,
                symbol TEXT,
                headline TEXT NOT NULL,
                provider_code TEXT NOT NULL,
                timestamp INTEGER NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sync_status (
                symbol TEXT NOT NULL,
                timeframe TEXT NOT NULL,
                latest_bar_time INTEGER NOT NULL,
                bar_count INTEGER NOT NULL,
                synced_at TEXT NOT NULL,
                PRIMARY KEY(symbol, timeframe)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS probe_cache (
                symbol TEXT NOT NULL,
                timeframe TEXT NOT NULL,
                earliest_bar_time INTEGER,
                latest_news_time INTEGER,
                PRIMARY KEY(symbol, timeframe)
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_klines_symbol_timeframe ON klines(symbol, timeframe)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_klines_timestamp ON klines(timestamp)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_news_timestamp ON news(timestamp)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_news_symbol ON news(symbol)")
        conn.commit()
        conn.close()

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._worker_thread = threading.Thread(target=self._db_worker, daemon=True)
        self._worker_thread.start()

    def stop(self) -> None:
        self._running = False
        self._write_queue.put(WriteRequest(type="STOP", data={}))
        if self._worker_thread:
            self._worker_thread.join(timeout=5)

    def _db_worker(self) -> None:
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")

        batch: list[WriteRequest] = []
        batch_size = 10
        last_flush = time.time()
        flush_interval = 0.1

        while self._running or not self._write_queue.empty():
            try:
                req = self._write_queue.get(timeout=0.05)
                if req.type == "STOP":
                    self._flush_batch(conn, batch)
                    break
                batch.append(req)

                if len(batch) >= batch_size or (time.time() - last_flush) >= flush_interval:
                    self._flush_batch(conn, batch)
                    batch = []
                    last_flush = time.time()
            except queue.Empty:
                if batch and (time.time() - last_flush) >= flush_interval:
                    self._flush_batch(conn, batch)
                    batch = []
                    last_flush = time.time()

            while True:
                try:
                    read_req = self._read_request_queue.get_nowait()
                    self._handle_read_request(conn, read_req)
                except queue.Empty:
                    break

        conn.close()

    def _flush_batch(self, conn: sqlite3.Connection, batch: list[WriteRequest]) -> None:
        if not batch:
            return
        conn.execute("BEGIN")
        try:
            klines = [r for r in batch if r.type == "kline"]
            if klines:
                conn.executemany("""
                    INSERT OR REPLACE INTO klines
                    (symbol, timeframe, timestamp, open, high, low, close, volume, bar_count, bar_time)
                    VALUES (:symbol, :timeframe, :timestamp, :open, :high, :low, :close, :volume, :bar_count, :bar_time)
                """, [r.data for r in klines])

            news_items = [r for r in batch if r.type == "news"]
            if news_items:
                conn.executemany("""
                    INSERT OR IGNORE INTO news
                    (article_id, symbol, headline, provider_code, timestamp)
                    VALUES (:article_id, :symbol, :headline, :provider_code, :timestamp)
                """, [r.data for r in news_items])

            statuses = [r for r in batch if r.type == "sync_status"]
            if statuses:
                conn.executemany("""
                    INSERT OR REPLACE INTO sync_status
                    (symbol, timeframe, latest_bar_time, bar_count, synced_at)
                    VALUES (:symbol, :timeframe, :latest_bar_time, :bar_count, :synced_at)
                """, [r.data for r in statuses])

            conn.commit()
        except Exception:
            conn.rollback()
            raise

    def _handle_read_request(self, conn: sqlite3.Connection, req: ReadRequest) -> None:
        result_queue = self._read_response_queues.get(req.id)
        if not result_queue:
            return

        try:
            if req.type == "get_latest_bar":
                cursor = conn.execute("""
                    SELECT symbol, timeframe, timestamp, open, high, low, close, volume, bar_count, bar_time
                    FROM klines
                    WHERE symbol = :symbol AND timeframe = :timeframe
                    ORDER BY timestamp DESC
                    LIMIT 1
                """, req.params)
                row = cursor.fetchone()
                if row:
                    result = KlineBar(
                        symbol=row[0], timeframe=row[1], timestamp=row[2],
                        open=row[3], high=row[4], low=row[5], close=row[6],
                        volume=row[7], bar_count=row[8], bar_time=datetime.fromisoformat(row[9])
                    )
                else:
                    result = None
                result_queue.put(result)

            elif req.type == "get_bar_count":
                cursor = conn.execute("""
                    SELECT COUNT(*) FROM klines
                    WHERE symbol = :symbol AND timeframe = :timeframe
                """, req.params)
                result = cursor.fetchone()[0]
                result_queue.put(result)

            elif req.type == "get_sync_status":
                cursor = conn.execute("""
                    SELECT symbol, timeframe, latest_bar_time, bar_count, synced_at
                    FROM sync_status
                    WHERE symbol = :symbol AND timeframe = :timeframe
                """, req.params)
                row = cursor.fetchone()
                if row:
                    result = SyncStatus(
                        symbol=row[0], timeframe=row[1], latest_bar_time=row[2],
                        bar_count=row[3], synced_at=datetime.fromisoformat(row[4])
                    )
                else:
                    result = None
                result_queue.put(result)

            elif req.type == "get_bars":
                cursor = conn.execute("""
                    SELECT symbol, timeframe, timestamp, open, high, low, close, volume, bar_count, bar_time
                    FROM klines
                    WHERE symbol = :symbol AND timeframe = :timeframe
                    AND timestamp >= :start_ts AND timestamp <= :end_ts
                    ORDER BY timestamp ASC
                """, req.params)
                result = [
                    KlineBar(
                        symbol=r[0], timeframe=r[1], timestamp=r[2],
                        open=r[3], high=r[4], low=r[5], close=r[6],
                        volume=r[7], bar_count=r[8], bar_time=datetime.fromisoformat(r[9])
                    ) for r in cursor.fetchall()
                ]
                result_queue.put(result)

            elif req.type == "get_news":
                cursor = conn.execute("""
                    SELECT article_id, symbol, headline, provider_code, timestamp
                    FROM news
                    WHERE symbol = :symbol
                    ORDER BY timestamp DESC
                    LIMIT :limit
                """, req.params)
                result = [
                    NewsItem(
                        article_id=r[0], symbol=r[1], headline=r[2],
                        provider_code=r[3], timestamp=r[4]
                    ) for r in cursor.fetchall()
                ]
                result_queue.put(result)

            elif req.type == "get_latest_bar_time":
                cursor = conn.execute("""
                    SELECT timestamp FROM klines
                    WHERE symbol = :symbol AND timeframe = :timeframe
                    ORDER BY timestamp DESC LIMIT 1
                """, req.params)
                row = cursor.fetchone()
                result = row[0] if row else None
                result_queue.put(result)

            elif req.type == "get_earliest_bar_time":
                cursor = conn.execute("""
                    SELECT earliest_bar_time FROM probe_cache
                    WHERE symbol = :symbol AND timeframe = :timeframe
                """, req.params)
                row = cursor.fetchone()
                result = row[0] if row else None
                result_queue.put(result)

            elif req.type == "set_earliest_bar_time":
                conn.execute("""
                    INSERT OR REPLACE INTO probe_cache (symbol, timeframe, earliest_bar_time)
                    VALUES (:symbol, :timeframe, :earliest_bar_time)
                """, req.params)
                result_queue.put(None)

            elif req.type == "get_latest_news_time":
                cursor = conn.execute("""
                    SELECT latest_news_time FROM probe_cache
                    WHERE symbol = :symbol AND timeframe = 'NEWS'
                """, req.params)
                row = cursor.fetchone()
                result = row[0] if row else None
                result_queue.put(result)

            else:
                result_queue.put(None)
        except Exception as e:
            result_queue.put(e)

    def write_kline(self, k: KlineBar) -> None:
        self._write_queue.put(WriteRequest(type="kline", data={
            "symbol": k.symbol,
            "timeframe": k.timeframe,
            "timestamp": k.timestamp,
            "open": k.open,
            "high": k.high,
            "low": k.low,
            "close": k.close,
            "volume": k.volume,
            "bar_count": k.bar_count,
            "bar_time": k.bar_time.isoformat(),
        }))

    def write_news(self, news: NewsItem) -> None:
        self._write_queue.put(WriteRequest(type="news", data={
            "article_id": news.article_id,
            "symbol": news.symbol,
            "headline": news.headline,
            "provider_code": news.provider_code,
            "timestamp": news.timestamp,
        }))

    def update_sync_status(self, status: SyncStatus) -> None:
        self._write_queue.put(WriteRequest(type="sync_status", data={
            "symbol": status.symbol,
            "timeframe": status.timeframe,
            "latest_bar_time": status.latest_bar_time,
            "bar_count": status.bar_count,
            "synced_at": status.synced_at.isoformat(),
        }))

    def get_latest_bar(self, symbol: str, timeframe: str) -> Optional[KlineBar]:
        req_id = f"{symbol}_{timeframe}_{time.time()}"
        resp_queue: queue.Queue = queue.Queue()
        self._read_response_queues[req_id] = resp_queue
        self._read_request_queue.put(ReadRequest(id=req_id, type="get_latest_bar", params={
            "symbol": symbol, "timeframe": timeframe
        }))
        try:
            return resp_queue.get(timeout=5)
        finally:
            self._read_response_queues.pop(req_id, None)

    def get_bar_count(self, symbol: str, timeframe: str) -> int:
        req_id = f"{symbol}_{timeframe}_{time.time()}"
        resp_queue: queue.Queue = queue.Queue()
        self._read_response_queues[req_id] = resp_queue
        self._read_request_queue.put(ReadRequest(id=req_id, type="get_bar_count", params={
            "symbol": symbol, "timeframe": timeframe
        }))
        try:
            return resp_queue.get(timeout=5)
        finally:
            self._read_response_queues.pop(req_id, None)

    def get_sync_status(self, symbol: str, timeframe: str) -> Optional[SyncStatus]:
        req_id = f"{symbol}_{timeframe}_{time.time()}"
        resp_queue: queue.Queue = queue.Queue()
        self._read_response_queues[req_id] = resp_queue
        self._read_request_queue.put(ReadRequest(id=req_id, type="get_sync_status", params={
            "symbol": symbol, "timeframe": timeframe
        }))
        try:
            return resp_queue.get(timeout=5)
        finally:
            self._read_response_queues.pop(req_id, None)

    def get_bars(self, symbol: str, timeframe: str, start_ts: int, end_ts: int) -> list[KlineBar]:
        req_id = f"{symbol}_{timeframe}_{start_ts}_{end_ts}_{time.time()}"
        resp_queue: queue.Queue = queue.Queue()
        self._read_response_queues[req_id] = resp_queue
        self._read_request_queue.put(ReadRequest(id=req_id, type="get_bars", params={
            "symbol": symbol, "timeframe": timeframe, "start_ts": start_ts, "end_ts": end_ts
        }))
        try:
            return resp_queue.get(timeout=10)
        finally:
            self._read_response_queues.pop(req_id, None)

    def get_news(self, symbol: str, limit: int = 100) -> list[NewsItem]:
        req_id = f"news_{symbol}_{time.time()}"
        resp_queue: queue.Queue = queue.Queue()
        self._read_response_queues[req_id] = resp_queue
        self._read_request_queue.put(ReadRequest(id=req_id, type="get_news", params={
            "symbol": symbol, "limit": limit
        }))
        try:
            return resp_queue.get(timeout=5)
        finally:
            self._read_response_queues.pop(req_id, None)

    def get_latest_bar_time(self, symbol: str, timeframe: str) -> Optional[int]:
        req_id = f"latest_bar_time_{symbol}_{timeframe}_{time.time()}"
        resp_queue: queue.Queue = queue.Queue()
        self._read_response_queues[req_id] = resp_queue
        self._read_request_queue.put(ReadRequest(id=req_id, type="get_latest_bar_time", params={
            "symbol": symbol, "timeframe": timeframe
        }))
        try:
            return resp_queue.get(timeout=5)
        finally:
            self._read_response_queues.pop(req_id, None)

    def get_earliest_bar_time(self, symbol: str, timeframe: str) -> Optional[int]:
        req_id = f"earliest_bar_time_{symbol}_{timeframe}_{time.time()}"
        resp_queue: queue.Queue = queue.Queue()
        self._read_response_queues[req_id] = resp_queue
        self._read_request_queue.put(ReadRequest(id=req_id, type="get_earliest_bar_time", params={
            "symbol": symbol, "timeframe": timeframe
        }))
        try:
            return resp_queue.get(timeout=5)
        finally:
            self._read_response_queues.pop(req_id, None)

    def set_earliest_bar_time(self, symbol: str, timeframe: str, earliest_bar_time: int) -> None:
        req_id = f"set_earliest_{symbol}_{timeframe}_{time.time()}"
        resp_queue: queue.Queue = queue.Queue()
        self._read_response_queues[req_id] = resp_queue
        self._read_request_queue.put(ReadRequest(id=req_id, type="set_earliest_bar_time", params={
            "symbol": symbol, "timeframe": timeframe, "earliest_bar_time": earliest_bar_time
        }))
        try:
            resp_queue.get(timeout=5)
        finally:
            self._read_response_queues.pop(req_id, None)

    def get_latest_news_time(self, symbol: str) -> Optional[int]:
        req_id = f"latest_news_time_{symbol}_{time.time()}"
        resp_queue: queue.Queue = queue.Queue()
        self._read_response_queues[req_id] = resp_queue
        self._read_request_queue.put(ReadRequest(id=req_id, type="get_latest_news_time", params={
            "symbol": symbol
        }))
        try:
            return resp_queue.get(timeout=5)
        finally:
            self._read_response_queues.pop(req_id, None)
