from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import threading
from collections.abc import Coroutine
from datetime import date, datetime, timezone
from typing import Any, Optional, TypeVar

from ib_insync import Forex, Future, IB, Index, Stock
from ib_insync.contract import Contract

from ibkr_datafetcher.config import GatewayConfig
from ibkr_datafetcher.types import KlineBar, NewsItem, SymbolConfig, Timeframe

logger = logging.getLogger(__name__)

T = TypeVar("T")


def _bar_date_to_datetime(bar_date: datetime | date | str) -> datetime:
    if isinstance(bar_date, datetime):
        return bar_date if bar_date.tzinfo else bar_date.replace(tzinfo=timezone.utc)
    if isinstance(bar_date, date):
        return datetime(bar_date.year, bar_date.month, bar_date.day, tzinfo=timezone.utc)
    s = str(bar_date).strip()
    for fmt in ("%Y%m%d  %H:%M:%S", "%Y%m%d %H:%M:%S", "%Y%m%d-%H:%M:%S", "%Y%m%d"):
        try:
            dt = datetime.strptime(s, fmt)
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    try:
        return datetime.fromtimestamp(int(s), tz=timezone.utc)
    except ValueError as e:
        msg = f"unparseable bar date: {bar_date!r}"
        raise ValueError(msg) from e


class IBKRClient:
    def __init__(self, config: GatewayConfig):
        self._config = config
        self._ib = IB()
        self._ib.RequestTimeout = 120
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._loop_ready = threading.Event()
        self._thread_lock = threading.Lock()

    def _ensure_loop_thread(self) -> None:
        with self._thread_lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._loop_ready.clear()

            def runner() -> None:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                self._loop = loop
                self._loop_ready.set()
                loop.run_forever()

            self._thread = threading.Thread(
                target=runner, daemon=True, name="ibkr-insync-loop"
            )
            self._thread.start()
            if not self._loop_ready.wait(timeout=10):
                msg = "IBKR event loop thread failed to start"
                raise RuntimeError(msg)

    def _run_coro(self, coro: Coroutine[Any, Any, T], timeout: float) -> T:
        if self._loop is None:
            msg = "event loop not running"
            raise RuntimeError(msg)
        fut = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return fut.result(timeout=timeout)

    async def _connect_async(self, timeout: float) -> None:
        await self._ib.connectAsync(
            self._config.host,
            self._config.port,
            self._config.client_id,
            timeout,
            readonly=True,
        )

    async def _is_connected_async(self) -> bool:
        return self._ib.isConnected()

    def connect(self, timeout: float = 30) -> bool:
        try:
            self._ensure_loop_thread()
            self._run_coro(self._connect_async(timeout), timeout + 15)
            return self._run_coro(self._is_connected_async(), 5)
        except (OSError, asyncio.TimeoutError, ConnectionRefusedError,
                RuntimeError, TimeoutError, concurrent.futures.TimeoutError):
            logger.exception("IBKR connect failed")
            return False

    def disconnect(self) -> None:
        loop = self._loop
        thread = self._thread
        if loop is None or thread is None or not thread.is_alive():
            self._loop = None
            self._thread = None
            self._ib = IB()
            self._ib.RequestTimeout = 120
            return
        try:
            if self._ib.isConnected():
                self._ib.disconnect()
        except (OSError, RuntimeError):
            logger.debug("IB disconnect raised", exc_info=True)
        try:
            loop.call_soon_threadsafe(loop.stop)
        except RuntimeError:
            pass
        thread.join(timeout=5)
        self._loop = None
        self._thread = None
        self._ib = IB()
        self._ib.RequestTimeout = 120

    def is_connected(self) -> bool:
        if self._loop is None or self._thread is None or not self._thread.is_alive():
            return False
        try:
            return self._run_coro(self._is_connected_async(), 5)
        except (OSError, RuntimeError, concurrent.futures.TimeoutError):
            return False

    def reconnect(self, max_retries: int = 3) -> bool:
        self.disconnect()
        for _ in range(max_retries):
            if self.connect():
                return True
        return False

    def make_contract(self, symbol_config: SymbolConfig) -> Contract:
        st = symbol_config.sec_type.upper()
        sym = symbol_config.symbol
        ex = symbol_config.exchange
        cur = symbol_config.currency
        if st == "STK":
            return Stock(sym, ex, cur)
        if st == "IND":
            return Index(sym, ex, cur)
        if st == "FUT":
            return Future(sym, "", ex, currency=cur)
        if st == "CASH":
            return Forex(symbol=sym, exchange=ex, currency=cur)
        msg = f"unsupported sec_type: {symbol_config.sec_type!r}"
        raise ValueError(msg)

    async def _qualify_async(self, contract: Contract) -> list[Contract]:
        return await self._ib.qualifyContractsAsync(contract)

    def qualify_contract(self, contract: Contract) -> int:
        if not self.is_connected():
            raise ConnectionError("not connected")
        qualified = self._run_coro(self._qualify_async(contract), 120)
        if not qualified:
            msg = f"contract not found: {contract}"
            raise ValueError(msg)
        c0 = qualified[0]
        cid = int(c0.conId)
        if cid <= 0:
            msg = f"invalid conId for contract: {contract}"
            raise ValueError(msg)
        return cid

    async def _historical_bars_async(
        self,
        contract: Contract,
        timeframe: Timeframe,
        end_date_time: str,
        duration: str,
        what_to_show: str,
    ) -> Any:
        return await self._ib.reqHistoricalDataAsync(
            contract,
            end_date_time or "",
            duration,
            timeframe.ibkr_bar_size,
            what_to_show,
            True,
            2,
            False,
        )

    def get_historical_bars(
        self,
        contract: Contract,
        timeframe: Timeframe,
        end_date_time: str = "",
        duration: Optional[str] = None,
        what_to_show: str = "TRADES",
    ) -> list[KlineBar]:
        if not self.is_connected():
            raise ConnectionError("not connected")
        dur = duration if duration is not None else timeframe.ibkr_max_duration
        bars = self._run_coro(
            self._historical_bars_async(
                contract, timeframe, end_date_time, dur, what_to_show
            ),
            120,
        )
        sym = contract.localSymbol or contract.symbol
        out: list[KlineBar] = []
        for b in bars:
            bar_time = _bar_date_to_datetime(b.date)
            ts = int(bar_time.timestamp())
            out.append(
                KlineBar(
                    symbol=sym,
                    timeframe=timeframe,
                    timestamp=ts,
                    open=float(b.open),
                    high=float(b.high),
                    low=float(b.low),
                    close=float(b.close),
                    volume=float(b.volume),
                    bar_count=int(b.barCount),
                    bar_time=bar_time,
                )
            )
        out.sort(key=lambda x: x.timestamp)
        return out

    async def _historical_news_async(
        self,
        con_id: int,
        provider_codes: str,
        start_time: Optional[str],
        end_time: Optional[str],
        total_results: int,
    ) -> Any:
        return await self._ib.reqHistoricalNewsAsync(
            con_id,
            provider_codes,
            start_time or "",
            end_time or "",
            total_results,
            [],
        )

    def get_historical_news(
        self,
        con_id: int,
        provider_codes: str = "BRFG+BRFUPDN+DJNL",
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        total_results: int = 100,
    ) -> list[NewsItem]:
        if not self.is_connected():
            raise ConnectionError("not connected")
        if con_id <= 0:
            return []
        raw = self._run_coro(
            self._historical_news_async(
                con_id, provider_codes, start_time, end_time, total_results
            ),
            30,
        )
        if raw is None:
            return []
        items = raw if isinstance(raw, list) else [raw]
        out: list[NewsItem] = []
        for h in items:
            bt = h.time
            if isinstance(bt, datetime):
                ts = int(
                    bt.timestamp()
                    if bt.tzinfo
                    else bt.replace(tzinfo=timezone.utc).timestamp()
                )
            else:
                ts = int(
                    datetime.combine(bt, datetime.min.time(), tzinfo=timezone.utc).timestamp()
                )
            out.append(
                NewsItem(
                    article_id=h.articleId,
                    symbol=None,
                    headline=h.headline,
                    provider_code=h.providerCode,
                    timestamp=ts,
                )
            )
        return out
