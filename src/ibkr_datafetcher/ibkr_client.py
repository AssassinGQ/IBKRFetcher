import logging
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

import ib_insync
from ib_insync import Contract, Forex, Future, Index, Stock

from ibkr_datafetcher.config import GatewayConfig, SymbolConfig
from ibkr_datafetcher.types import KlineBar, NewsItem, Timeframe

logger = logging.getLogger(__name__)


class IBKRClient:
    def __init__(self, config: GatewayConfig):
        self._config = config
        self._ib: Optional[ib_insync.IB] = None
        self._loop_thread: Optional[threading.Thread] = None
        self._connected = False
        self._lock = threading.Lock()

    def connect(self, timeout: float = 30) -> bool:
        with self._lock:
            if self._connected and self._ib and self._ib.isConnected():
                return True

            self._ib = ib_insync.IB()
            try:
                self._ib.connect(
                    host=self._config.host,
                    port=self._config.port,
                    clientId=self._config.client_id,
                    timeout=timeout,
                )
                self._connected = True

                self._loop_thread = threading.Thread(
                    target=self._run_event_loop,
                    name="IBKR-EventLoop",
                    daemon=True,
                )
                self._loop_thread.start()
                logger.info(
                    "Connected to IBKR Gateway at %s:%s (client_id=%s)",
                    self._config.host,
                    self._config.port,
                    self._config.client_id,
                )
                return True
            except Exception as e:
                logger.error("Failed to connect to IBKR Gateway: %s", e)
                self._connected = False
                self._ib = None
                return False

    def disconnect(self) -> None:
        with self._lock:
            if self._ib and self._ib.isConnected():
                self._ib.disconnect()
                logger.info("Disconnected from IBKR Gateway")
            self._connected = False
            self._ib = None
            self._loop_thread = None

    def is_connected(self) -> bool:
        with self._lock:
            return self._connected and self._ib is not None and self._ib.isConnected()

    def reconnect(self, max_retries: int = 3) -> bool:
        for attempt in range(max_retries):
            logger.info("Reconnection attempt %d/%d", attempt + 1, max_retries)
            self.disconnect()
            time.sleep(2)
            if self.connect():
                return True
            time.sleep(5)
        logger.error("Failed to reconnect after %d attempts", max_retries)
        return False

    def _run_event_loop(self) -> None:
        if self._ib is None:
            return
        try:
            self._ib.run()
        except Exception as e:
            logger.error("IBKR event loop error: %s", e)

    def make_contract(self, symbol_config: SymbolConfig) -> Contract:
        sec_type = symbol_config.sec_type.upper()
        symbol = symbol_config.symbol
        exchange = symbol_config.exchange
        currency = symbol_config.currency

        if sec_type == "STK":
            contract = Stock(symbol, exchange, currency)
        elif sec_type == "IND":
            contract = Index(symbol, exchange, currency)
        elif sec_type == "FUT":
            contract = Future(symbol=symbol, exchange=exchange, currency=currency)
        elif sec_type == "CASH":
            contract = Forex(pair=symbol, exchange=exchange)
        else:
            contract = Stock(symbol, exchange, currency)

        logger.debug("Created contract: %s %s %s %s", sec_type, symbol, exchange, currency)
        return contract

    def qualify_contract(self, contract: Contract) -> int:
        if not self.is_connected():
            raise ConnectionError("Not connected to IBKR Gateway")

        qualified_list = self._ib.qualifyContracts(contract)
        if not qualified_list or not qualified_list[0].conId:
            raise ValueError(f"Contract {contract.symbol} cannot be qualified")
        qualified = qualified_list[0]
        logger.debug("Contract qualified: %s conId=%d", contract.symbol, qualified.conId)
        return qualified.conId

    def get_historical_bars(
        self,
        contract: Contract,
        timeframe: Timeframe,
        end_date_time: str = "",
        duration: Optional[str] = None,
        what_to_show: str = "TRADES",
    ) -> list[KlineBar]:
        if not self.is_connected():
            raise ConnectionError("Not connected to IBKR Gateway")

        if not end_date_time:
            end_dt = datetime.now(timezone.utc)
        else:
            try:
                end_dt = datetime.strptime(end_date_time, "%Y%m%d %H:%M:%S")
                end_dt = end_dt.replace(tzinfo=timezone.utc)
            except ValueError:
                end_dt = datetime.now(timezone.utc)

        duration_str = duration or timeframe.ibkr_max_duration
        bar_size = timeframe.ibkr_bar_size

        try:
            bars = self._ib.reqHistoricalData(
                contract=contract,
                endDateTime=end_dt,
                durationStr=duration_str,
                barSizeSetting=bar_size,
                whatToShow=what_to_show,
                useRTH=True,
                formatDate=2,
                keepUpToDate=False,
            )
        except Exception as e:
            logger.error("reqHistoricalData failed: %s", e)
            return []

        result = []
        for bar in bars:
            bar_time = bar.date
            if isinstance(bar_time, (int, float)):
                bar_time = datetime.fromtimestamp(bar_time, tz=timezone.utc)
            kline_bar = KlineBar(
                symbol=contract.symbol,
                timeframe=timeframe.value,
                timestamp=int(bar_time.timestamp()),
                open=float(bar.open),
                high=float(bar.high),
                low=float(bar.low),
                close=float(bar.close),
                volume=float(bar.volume),
                bar_count=int(bar.barCount) if hasattr(bar, 'barCount') else 0,
                bar_time=bar_time,
            )
            result.append(kline_bar)

        logger.debug(
            "Fetched %d bars for %s %s from %s",
            len(result),
            contract.symbol,
            timeframe.value,
            end_date_time or "now",
        )
        return result

    def get_historical_news(
        self,
        con_id: int,
        provider_codes: str = "BRFG+BRFUPDN+DJNL",
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        total_results: int = 100,
    ) -> list[NewsItem]:
        if not self.is_connected():
            raise ConnectionError("Not connected to IBKR Gateway")

        if not start_time:
            start_dt = datetime.now(timezone.utc) - timedelta(days=30)
            start_str = start_dt.strftime("%Y%m%d-%H:%M:%S")
        else:
            start_str = start_time

        if not end_time:
            end_str = ""
        else:
            end_str = end_time

        try:
            historical_news = self._ib.reqHistoricalNews(
                conId=con_id,
                providerCodes=provider_codes,
                startDateTime=start_str,
                endDateTime=end_str,
                totalResults=total_results,
            )
        except Exception as e:
            logger.error("reqHistoricalNews failed: %s", e)
            return []

        news_list = []
        if historical_news and hasattr(historical_news, 'news'):
            for news_item in historical_news.news:
                item = NewsItem(
                    article_id=str(news_item.articleId),
                    symbol="",
                    headline=str(news_item.headline),
                    provider_code=str(news_item.providerCode),
                    timestamp=int(news_item.time.timestamp()) if hasattr(news_item.time, 'timestamp') else 0,
                )
                news_list.append(item)

        logger.debug("Fetched %d news items for conId=%d", len(news_list), con_id)
        return news_list
