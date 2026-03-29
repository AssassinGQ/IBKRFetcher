"""
Mock IBKR Gateway server implementing TWS API binary protocol.

Listens on a configurable port (default 4002) and responds to ib_insync client
connections with deterministic fake data. Supports concurrent client connections.

Usage:
    python -m mock_gateway [--port 4002]
    python mock_gateway/ibkr_mock_server.py [--port 4002]
"""

import asyncio
import logging
import struct
import argparse
import signal
import sys
from datetime import datetime
from typing import Optional

from mock_gateway.fake_data import (
    generate_bars, generate_news, generate_news_bulletins,
    generate_smart_components, lookup_contract, FAKE_NEWS_PROVIDERS,
    KNOWN_CONTRACTS, _base_price, _is_volatility_index,
)

logger = logging.getLogger("mock_gateway")

SERVER_VERSION = 176
MANAGED_ACCOUNTS = "DU0000001"

# TWS API incoming message IDs (client -> server)
MSG_REQ_MKT_DATA = 1
MSG_CANCEL_MKT_DATA = 2
MSG_REQ_OPEN_ORDERS = 5
MSG_REQ_ACCOUNT_UPDATES = 6
MSG_REQ_EXECUTIONS = 7
MSG_REQ_CONTRACT_DETAILS = 9
MSG_REQ_MKT_DEPTH = 10
MSG_REQ_NEWS_BULLETINS = 12
MSG_CANCEL_NEWS_BULLETINS = 13
MSG_REQ_AUTO_OPEN_ORDERS = 15
MSG_CANCEL_MKT_DEPTH = 17
MSG_REQ_HISTORICAL_DATA = 20
MSG_CANCEL_HISTORICAL_DATA = 25
MSG_REQ_POSITIONS = 61
MSG_START_API = 71
MSG_REQ_ACCOUNT_UPDATES_MULTI = 76
MSG_REQ_SMART_COMPONENTS = 83
MSG_REQ_NEWS_PROVIDERS = 85
MSG_REQ_HISTORICAL_NEWS = 86
MSG_REQ_COMPLETED_ORDERS = 99

# TWS API outgoing message IDs (server -> client)
OUT_PRICE_SIZE_TICK = 1
OUT_TICK_SIZE = 2
OUT_ERR_MSG = 4
OUT_NEXT_VALID_ID = 9
OUT_CONTRACT_DETAILS = 10
OUT_UPDATE_MKT_DEPTH = 12
OUT_UPDATE_MKT_DEPTH_L2 = 13
OUT_UPDATE_NEWS_BULLETIN = 14
OUT_MANAGED_ACCOUNTS = 15
OUT_HISTORICAL_DATA = 17
OUT_CONTRACT_DETAILS_END = 52
OUT_OPEN_ORDER_END = 53
OUT_ACCOUNT_DOWNLOAD_END = 54
OUT_EXEC_DETAILS_END = 55
OUT_TICK_SNAPSHOT_END = 57
OUT_POSITION_END = 62
OUT_POSITION_MULTI_END = 72
OUT_ACCOUNT_UPDATE_MULTI_END = 74
OUT_SMART_COMPONENTS = 82
OUT_NEWS_PROVIDERS = 85
OUT_HISTORICAL_NEWS = 86
OUT_HISTORICAL_NEWS_END = 87
OUT_COMPLETED_ORDERS_END = 102


def _encode_msg(*fields) -> bytes:
    """Encode fields into a TWS API message with 4-byte length prefix."""
    parts = []
    for f in fields:
        if f is None:
            parts.append("")
        else:
            parts.append(str(f))
    body = "\0".join(parts) + "\0"
    encoded = body.encode()
    return struct.pack(">I", len(encoded)) + encoded


class MockClientHandler(asyncio.Protocol):
    """Handles a single ib_insync client connection."""

    def __init__(self, server: "MockIBKRServer"):
        self.server = server
        self.transport: Optional[asyncio.Transport] = None
        self.client_id: Optional[int] = None
        self._buffer = b""
        self._handshake_done = False
        self._api_started = False

    def connection_made(self, transport: asyncio.Transport):
        peer = transport.get_extra_info("peername")
        logger.info("Client connected from %s", peer)
        self.transport = transport

    def connection_lost(self, exc):
        logger.info("Client %s disconnected", self.client_id)
        if self.client_id is not None:
            self.server.remove_client(self.client_id)

    def data_received(self, data: bytes):
        self._buffer += data
        self._process_buffer()

    def _process_buffer(self):
        while self._buffer:
            if not self._handshake_done:
                self._handle_handshake()
                return

            if len(self._buffer) < 4:
                return
            msg_len = struct.unpack(">I", self._buffer[:4])[0]
            if len(self._buffer) < 4 + msg_len:
                return

            msg_body = self._buffer[4:4 + msg_len].decode(errors="backslashreplace")
            self._buffer = self._buffer[4 + msg_len:]

            fields = msg_body.split("\0")
            if fields and fields[-1] == "":
                fields.pop()

            if fields:
                self._dispatch(fields)

    def _handle_handshake(self):
        if len(self._buffer) < 4:
            return
        api_marker = b"API\0"
        idx = self._buffer.find(api_marker)
        if idx < 0:
            return

        self._buffer = self._buffer[idx + len(api_marker):]

        if len(self._buffer) < 4:
            return
        msg_len = struct.unpack(">I", self._buffer[:4])[0]
        if len(self._buffer) < 4 + msg_len:
            return
        version_msg = self._buffer[4:4 + msg_len].decode(errors="backslashreplace")
        self._buffer = self._buffer[4 + msg_len:]

        logger.debug("Handshake version msg: %s", version_msg)

        conn_time = datetime.now().strftime("%Y%m%d %H:%M:%S")
        response = f"{SERVER_VERSION}\0{conn_time}\0".encode()
        self.transport.write(struct.pack(">I", len(response)) + response)
        self._handshake_done = True

        self._process_buffer()

    def _dispatch(self, fields: list[str]):
        try:
            msg_id = int(fields[0])
        except (ValueError, IndexError):
            logger.warning("Invalid message: %s", fields)
            return

        handler = {
            MSG_START_API: self._on_start_api,
            MSG_REQ_CONTRACT_DETAILS: self._on_req_contract_details,
            MSG_REQ_HISTORICAL_DATA: self._on_req_historical_data,
            MSG_REQ_MKT_DATA: self._on_req_mkt_data,
            MSG_CANCEL_MKT_DATA: self._on_noop,
            MSG_REQ_MKT_DEPTH: self._on_req_mkt_depth,
            MSG_CANCEL_MKT_DEPTH: self._on_noop,
            MSG_REQ_NEWS_BULLETINS: self._on_req_news_bulletins,
            MSG_CANCEL_NEWS_BULLETINS: self._on_noop,
            MSG_REQ_NEWS_PROVIDERS: self._on_req_news_providers,
            MSG_REQ_HISTORICAL_NEWS: self._on_req_historical_news,
            MSG_REQ_SMART_COMPONENTS: self._on_req_smart_components,
            MSG_CANCEL_HISTORICAL_DATA: self._on_noop,
            MSG_REQ_POSITIONS: self._on_req_positions,
            MSG_REQ_OPEN_ORDERS: self._on_req_open_orders,
            MSG_REQ_COMPLETED_ORDERS: self._on_req_completed_orders,
            MSG_REQ_ACCOUNT_UPDATES: self._on_req_account_updates,
            MSG_REQ_ACCOUNT_UPDATES_MULTI: self._on_req_account_updates_multi,
            MSG_REQ_EXECUTIONS: self._on_req_executions,
            MSG_REQ_AUTO_OPEN_ORDERS: self._on_noop,
        }.get(msg_id)

        if handler:
            handler(fields)
        else:
            logger.debug("Unhandled message ID %d: %s", msg_id, fields[:5])

    def _send(self, *fields):
        if self.transport and not self.transport.is_closing():
            self.transport.write(_encode_msg(*fields))

    def _send_error(self, req_id: int, code: int, msg: str):
        self._send(OUT_ERR_MSG, "2", req_id, code, msg, "")

    def _on_noop(self, fields):
        pass

    def _on_req_positions(self, fields):
        self._send(OUT_POSITION_END, "1")

    def _on_req_open_orders(self, fields):
        self._send(OUT_OPEN_ORDER_END, "1")

    def _on_req_completed_orders(self, fields):
        self._send(OUT_COMPLETED_ORDERS_END)

    def _on_req_account_updates(self, fields):
        # fields: [6, version, subscribe, acctCode]
        acct = fields[3] if len(fields) > 3 else MANAGED_ACCOUNTS
        self._send(OUT_ACCOUNT_DOWNLOAD_END, "1", acct)

    def _on_req_account_updates_multi(self, fields):
        # fields: [76, version, reqId, account, modelCode, ledgerAndNLV]
        req_id = int(fields[2]) if len(fields) > 2 else 0
        self._send(OUT_ACCOUNT_UPDATE_MULTI_END, "1", req_id)

    def _on_req_executions(self, fields):
        # fields: [7, version, reqId, ...]
        req_id = int(fields[2]) if len(fields) > 2 else 0
        self._send(OUT_EXEC_DETAILS_END, "1", req_id)

    def _on_start_api(self, fields):
        # fields: [71, version, clientId, optCapab]
        if len(fields) >= 3:
            self.client_id = int(fields[2])
        else:
            self.client_id = 0
        logger.info("startApi from client %d", self.client_id)
        self.server.add_client(self.client_id, self)
        self._api_started = True

        self._send(OUT_NEXT_VALID_ID, "1", "1")
        self._send(OUT_MANAGED_ACCOUNTS, "1", MANAGED_ACCOUNTS)

    def _on_req_contract_details(self, fields):
        # send format: [9, 8, reqId, <contract>, includeExpired, secIdType, secId, issuerId]
        # <contract> expands to: conId, symbol, secType, lastTradeDate, strike,
        #   right, multiplier, exchange, primaryExchange, currency, localSymbol, tradingClass
        # So: fields = [9, 8, reqId, conId, symbol, secType, lastTradeDate, strike,
        #               right, multiplier, exchange, primaryExchange, currency, ...]
        req_id = int(fields[2])
        symbol = fields[4] if len(fields) > 4 else ""
        s_type = fields[5] if len(fields) > 5 else "STK"
        exch = fields[10] if len(fields) > 10 else "SMART"
        curr = fields[12] if len(fields) > 12 else "USD"

        contract_info = lookup_contract(symbol, s_type, exch, curr)
        if not contract_info:
            self._send_error(req_id, 200,
                             f"No security definition for {symbol} {s_type}")
            self._send(OUT_CONTRACT_DETAILS_END, "1", req_id)
            return

        c_con_id = contract_info["conId"]
        c_exchange = contract_info["exchange"]
        c_primary = contract_info.get("primaryExchange", "")

        # For serverVersion >= 164, no version field after msgId
        # Decoder reads: _, reqId, symbol, secType, lastTimes, strike, right,
        #   exchange, currency, localSymbol, marketName, tradingClass, conId, minTick,
        #   ...then multiplier, orderTypes, validExchanges, priceMagnifier, underConId,
        #   longName, primaryExchange, contractMonth, industry, category, subcategory,
        #   timeZoneId, tradingHours, liquidHours, evRule, evMultiplier, numSecIds,
        #   ...then aggGroup, underSymbol, underSecType, marketRuleIds,
        #   realExpirationDate, stockType, minSize, sizeIncrement, suggestedSizeIncrement
        detail_fields = [
            OUT_CONTRACT_DETAILS,
            req_id,
            symbol,                # c.symbol
            s_type,                # c.secType
            "",                    # lastTimes (lastTradeDateOrContractMonth)
            "0",                   # c.strike
            "",                    # c.right
            c_exchange,            # c.exchange
            curr,                  # c.currency
            symbol,                # c.localSymbol
            symbol,                # cd.marketName
            "",                    # c.tradingClass
            c_con_id,              # c.conId
            "0.01",                # cd.minTick
            # --- after minTick ---
            "",                    # c.multiplier
            "",                    # cd.orderTypes
            exch,                  # cd.validExchanges
            "0",                   # cd.priceMagnifier
            "0",                   # cd.underConId
            symbol,                # cd.longName
            c_primary,             # c.primaryExchange
            "",                    # cd.contractMonth
            "",                    # cd.industry
            "",                    # cd.category
            "",                    # cd.subcategory
            "US/Eastern",          # cd.timeZoneId
            "",                    # cd.tradingHours
            "",                    # cd.liquidHours
            "",                    # cd.evRule
            "0",                   # cd.evMultiplier
            "0",                   # numSecIds
            # --- after numSecIds ---
            "0",                   # cd.aggGroup
            "",                    # cd.underSymbol
            "",                    # cd.underSecType
            "",                    # cd.marketRuleIds
            "",                    # cd.realExpirationDate
            "",                    # cd.stockType
            # --- serverVersion >= 164 ---
            "0",                   # cd.minSize
            "1",                   # cd.sizeIncrement
            "100",                 # cd.suggestedSizeIncrement
        ]
        self._send(*detail_fields)
        # contractDetailsEnd: decoder skip=2, reads [int] -> reqId
        self._send(OUT_CONTRACT_DETAILS_END, "1", req_id)

    def _on_req_historical_data(self, fields):
        # send format: [20, reqId, <contract>, includeExpired,
        #               endDateTime, barSizeSetting, durationStr, useRTH,
        #               whatToShow, formatDate, keepUpToDate, chartOptions]
        # <contract> = conId, symbol, secType, lastTradeDate, strike,
        #              right, multiplier, exchange, primaryExchange, currency,
        #              localSymbol, tradingClass
        # indices:   0=20, 1=reqId, 2=conId, 3=symbol, 4=secType, 5..13=contract fields,
        #            14=includeExpired, 15=endDateTime, 16=barSizeSetting,
        #            17=durationStr, 18=useRTH, 19=whatToShow, 20=formatDate
        req_id = int(fields[1])
        symbol = fields[3] if len(fields) > 3 else ""

        end_dt_str = fields[15] if len(fields) > 15 else ""
        bar_size = fields[16] if len(fields) > 16 else "1 day"
        duration_str = fields[17] if len(fields) > 17 else "1 D"
        what_to_show = fields[19] if len(fields) > 19 else "TRADES"
        format_date_str = fields[20] if len(fields) > 20 else "2"

        end_dt = None
        if end_dt_str:
            for fmt in ("%Y%m%d %H:%M:%S", "%Y%m%d  %H:%M:%S", "%Y%m%d-%H:%M:%S",
                        "%Y%m%d %H:%M:%S %Z"):
                try:
                    end_dt = datetime.strptime(end_dt_str.split(" ")[0] + " " +
                                               end_dt_str.split(" ")[-1]
                                               if " " in end_dt_str
                                               else end_dt_str,
                                               fmt)
                    break
                except ValueError:
                    continue
            if end_dt is None:
                try:
                    end_dt = datetime.strptime(end_dt_str[:15], "%Y%m%d %H:%M:%S")
                except ValueError:
                    end_dt = None

        if end_dt and end_dt.year < 1950:
            self._send(OUT_HISTORICAL_DATA, req_id, "", "", "0")
            return

        format_date = int(format_date_str) if format_date_str.isdigit() else 2
        bars = generate_bars(symbol, bar_size, duration_str, end_dt,
                             what_to_show, format_date)

        if not bars:
            self._send(OUT_HISTORICAL_DATA, req_id, "", "", "0")
            return

        start_date = bars[0].date if bars else ""
        end_date = bars[-1].date if bars else ""

        bar_fields = [OUT_HISTORICAL_DATA, req_id, start_date, end_date, len(bars)]
        for b in bars:
            bar_fields.extend([
                b.date, b.open, b.high, b.low, b.close,
                b.volume, b.average, b.bar_count,
            ])
        self._send(*bar_fields)

    def _on_req_mkt_data(self, fields):
        # send format: [1, 11, reqId, <contract>, ..., genericTickList, snapshot, ...]
        # <contract> = conId, symbol, secType, lastTradeDate, strike,
        #              right, multiplier, exchange, primaryExchange, currency,
        #              localSymbol, tradingClass
        req_id = int(fields[2])
        symbol = fields[4] if len(fields) > 4 else ""

        base = _base_price(symbol)
        is_vol = _is_volatility_index(symbol)

        if is_vol:
            spread = base * 0.005
        else:
            spread = base * 0.001

        # Tick types: 1=bid, 2=ask, 4=last, 6=high, 7=low, 9=close
        bid = round(base - spread, 2)
        ask = round(base + spread, 2)
        last = round(base, 2)
        high = round(base * 1.01, 2)
        low = round(base * 0.99, 2)
        close_val = round(base * 0.998, 2)

        self._send(OUT_PRICE_SIZE_TICK, "6", req_id, 1, bid, 100, 0)
        self._send(OUT_PRICE_SIZE_TICK, "6", req_id, 2, ask, 100, 0)
        self._send(OUT_PRICE_SIZE_TICK, "6", req_id, 4, last, 200, 0)
        self._send(OUT_PRICE_SIZE_TICK, "6", req_id, 6, high, 0, 0)
        self._send(OUT_PRICE_SIZE_TICK, "6", req_id, 7, low, 0, 0)
        self._send(OUT_PRICE_SIZE_TICK, "6", req_id, 9, close_val, 0, 0)

        self._send(OUT_TICK_SNAPSHOT_END, "1", req_id)

    def _on_cancel_mkt_data(self, fields):
        pass

    def _on_req_mkt_depth(self, fields):
        # send format: [10, 5, reqId, conId, symbol, secType, lastTradeDate, strike,
        #               right, multiplier, exchange, primaryExchange, currency,
        #               localSymbol, tradingClass, numRows, isSmartDepth, options]
        req_id = int(fields[2])
        symbol = fields[4] if len(fields) > 4 else ""

        base = _base_price(symbol)
        spread = base * 0.001

        levels = 5
        for i in range(levels):
            bid_price = round(base - spread * (i + 1), 2)
            ask_price = round(base + spread * (i + 1), 2)
            bid_size = (5 - i) * 100
            ask_size = (5 - i) * 100

            # Format: [msgId, version, reqId, position, marketMaker, operation, side, price, size, isSmartDepth]
            # Decoder skip=2 reads: [int, int, str, int, int, float, float, bool]
            self._send(OUT_UPDATE_MKT_DEPTH_L2, "1", req_id, i, "", 0, 1,
                       bid_price, bid_size, 1)
            self._send(OUT_UPDATE_MKT_DEPTH_L2, "1", req_id, i, "", 0, 0,
                       ask_price, ask_size, 1)

    def _on_cancel_mkt_depth(self, fields):
        pass

    def _on_req_news_bulletins(self, fields):
        # Response: [14, version, msgId, msgType, message, exchange]
        # Decoder skip=2 then reads [int, int, str, str]
        bulletins = generate_news_bulletins()
        for b in bulletins:
            self._send(OUT_UPDATE_NEWS_BULLETIN, "1",
                       b["msgId"], b["msgType"], b["message"], b["exchange"])

    def _on_cancel_news_bulletins(self, fields):
        pass

    def _on_req_news_providers(self, fields):
        prov_fields = [OUT_NEWS_PROVIDERS, len(FAKE_NEWS_PROVIDERS)]
        for code, name in FAKE_NEWS_PROVIDERS:
            prov_fields.extend([code, name])
        self._send(*prov_fields)

    def _on_req_historical_news(self, fields):
        # fields: [86, reqId, conId, providerCodes, startDateTime, endDateTime,
        #          totalResults, options]
        req_id = int(fields[1])
        con_id = int(fields[2]) if len(fields) > 2 and fields[2] else 0
        start_dt_str = fields[4] if len(fields) > 4 else ""
        end_dt_str = fields[5] if len(fields) > 5 else ""
        total_results = int(fields[6]) if len(fields) > 6 and fields[6] else 5

        symbol = self._resolve_symbol_from_conid(con_id)

        start_dt = None
        end_dt = None
        for dt_str, name in [(start_dt_str, "start"), (end_dt_str, "end")]:
            if dt_str:
                for fmt in ("%Y%m%d-%H:%M:%S", "%Y%m%d %H:%M:%S"):
                    try:
                        parsed = datetime.strptime(dt_str, fmt)
                        if name == "start":
                            start_dt = parsed
                        else:
                            end_dt = parsed
                        break
                    except ValueError:
                        continue

        news = generate_news(con_id, symbol, total_results, start_dt, end_dt)

        for item in news:
            self._send(OUT_HISTORICAL_NEWS, req_id, item.time,
                       item.provider_code, item.article_id, item.headline)

        self._send(OUT_HISTORICAL_NEWS_END, req_id, 0)

    def _on_req_smart_components(self, fields):
        # fields: [83, reqId, bboExchange]
        req_id = int(fields[1])
        exchange_code = fields[2] if len(fields) > 2 else ""

        components = generate_smart_components(exchange_code)
        comp_fields = [OUT_SMART_COMPONENTS, req_id, len(components)]
        for c in components:
            comp_fields.extend([c.bit_number, c.exchange, c.exchange_letter])
        self._send(*comp_fields)

    def _resolve_symbol_from_conid(self, con_id: int) -> str:
        for key, info in KNOWN_CONTRACTS.items():
            if info["conId"] == con_id:
                return key.split(":", maxsplit=1)[0]
        return "UNKNOWN"


class MockIBKRServer:
    """Async TCP server that speaks the TWS API protocol."""

    def __init__(self, host: str = "127.0.0.1", port: int = 4002):
        self.host = host
        self.port = port
        self.clients: dict[int, MockClientHandler] = {}
        self._server: Optional[asyncio.Server] = None

    def add_client(self, client_id: int, handler: MockClientHandler):
        self.clients[client_id] = handler
        logger.info("Client %d registered (total: %d)", client_id, len(self.clients))

    def remove_client(self, client_id: int):
        self.clients.pop(client_id, None)
        logger.info("Client %d removed (total: %d)", client_id, len(self.clients))

    async def start(self):
        loop = asyncio.get_event_loop()
        self._server = await loop.create_server(
            lambda: MockClientHandler(self), self.host, self.port,
            reuse_address=True, start_serving=True,
        )
        logger.info("Mock IBKR Gateway listening on %s:%d", self.host, self.port)

    async def stop(self):
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            logger.info("Mock IBKR Gateway stopped")

    async def serve_forever(self):
        await self.start()
        try:
            await self._server.serve_forever()
        except asyncio.CancelledError:
            pass
        finally:
            await self.stop()


async def _run_server(host: str, port: int):
    server = MockIBKRServer(host, port)
    await server.start()

    stop_event = asyncio.Event()

    def _signal_handler():
        logger.info("Received shutdown signal")
        stop_event.set()

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _signal_handler)
        except NotImplementedError:
            pass

    try:
        await stop_event.wait()
    finally:
        await server.stop()


def main():
    parser = argparse.ArgumentParser(description="Mock IBKR Gateway Server")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host")
    parser.add_argument("--port", type=int, default=4002, help="Bind port")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    args = parser.parse_args()

    level = logging.DEBUG if args.debug else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stdout,
    )

    logger.info("Starting Mock IBKR Gateway on %s:%d", args.host, args.port)
    try:
        asyncio.run(_run_server(args.host, args.port))
    except KeyboardInterrupt:
        logger.info("Shutdown by KeyboardInterrupt")


if __name__ == "__main__":
    main()
