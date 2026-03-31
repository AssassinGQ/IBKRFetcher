#!/usr/bin/env python3
"""Test fetching GOOGL data from real IB Gateways (dual-gateway mode).

- Live gateway (ib-live-gateway:4003) for K-line data
- Paper gateway (ib-gateway:4004) for news data
"""
from __future__ import annotations

import sys
import os
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from ibkr_datafetcher.config import GatewayConfig
from ibkr_datafetcher.ibkr_client import IBKRClient
from ibkr_datafetcher.types import SymbolConfig, Timeframe

GOOGL = SymbolConfig(
    symbol="GOOGL", name="Alphabet Inc.", sec_type="STK",
    exchange="SMART", currency="USD", what_to_show="TRADES",
)

LIVE_GW = GatewayConfig(host="ib-live-gateway", port=4003, client_id=10)
PAPER_GW = GatewayConfig(host="ib-gateway", port=4004, client_id=11)


def test_kline(client: IBKRClient, contract, con_id: int) -> None:
    print("2. Fetching daily bars (last 5 days)...")
    t0 = time.time()
    try:
        bars_d1 = client.get_historical_bars(
            contract, Timeframe.D1, duration="5 D", what_to_show="TRADES",
        )
        elapsed = time.time() - t0
        print("   Got %d daily bars in %.1fs" % (len(bars_d1), elapsed))
        for b in bars_d1:
            dt = b.bar_time.strftime("%Y-%m-%d")
            print("   %s O=%.2f H=%.2f L=%.2f C=%.2f V=%.0f" % (
                dt, b.open, b.high, b.low, b.close, b.volume))
    except Exception as e:
        print("   FAILED: %s (took %.1fs)" % (e, time.time() - t0))

    print("\n" + "=" * 60)
    print("3. Fetching 1-hour bars (last 1 day)...")
    t0 = time.time()
    try:
        bars_h1 = client.get_historical_bars(
            contract, Timeframe.H1, duration="1 D", what_to_show="TRADES",
        )
        elapsed = time.time() - t0
        print("   Got %d hourly bars in %.1fs" % (len(bars_h1), elapsed))
        for b in bars_h1[:5]:
            dt = b.bar_time.strftime("%Y-%m-%d %H:%M")
            print("   %s O=%.2f C=%.2f V=%.0f" % (dt, b.open, b.close, b.volume))
    except Exception as e:
        print("   FAILED: %s (took %.1fs)" % (e, time.time() - t0))


def test_news(client: IBKRClient, con_id: int) -> None:
    print("4. Fetching historical news for GOOGL (conId=%d)..." % con_id)
    t0 = time.time()
    try:
        news = client.get_historical_news(con_id, total_results=10)
        elapsed = time.time() - t0
        print("   Got %d news items in %.1fs" % (len(news), elapsed))
        for i, n in enumerate(news[:5]):
            ts_str = time.strftime("%Y-%m-%d %H:%M", time.gmtime(n.timestamp))
            print("   [%d] %s | %s | %s" % (i + 1, ts_str, n.provider_code, n.headline[:60]))
    except Exception as e:
        print("   FAILED: %s (took %.1fs)" % (e, time.time() - t0))


def main():
    live_client = IBKRClient(LIVE_GW)
    paper_client = IBKRClient(PAPER_GW)

    print("=" * 60)
    print("Connecting to LIVE gateway at %s:%d..." % (LIVE_GW.host, LIVE_GW.port))
    if not live_client.connect(timeout=60):
        print("FAILED to connect to live gateway.")
        sys.exit(1)
    print("Live gateway connected!\n")

    print("Connecting to PAPER gateway at %s:%d..." % (PAPER_GW.host, PAPER_GW.port))
    if not paper_client.connect(timeout=60):
        print("FAILED to connect to paper gateway.")
        live_client.disconnect()
        sys.exit(1)
    print("Paper gateway connected!\n")

    try:
        print("=" * 60)
        print("1. Qualifying GOOGL contract (via live gateway)...")
        contract = live_client.make_contract(GOOGL)
        con_id = live_client.qualify_contract(contract)
        print("   Qualified! conId = %d" % con_id)
        print("   symbol=%s exchange=%s primary=%s currency=%s" % (
            contract.symbol, contract.exchange,
            contract.primaryExchange, contract.currency))

        print("\n" + "=" * 60)
        print("[LIVE GATEWAY] K-line data")
        print("=" * 60)
        test_kline(live_client, contract, con_id)

        print("\n" + "=" * 60)
        print("[PAPER GATEWAY] News data")
        print("=" * 60)
        test_news(paper_client, con_id)

        print("\n" + "=" * 60)
        print("DONE!")

    except Exception as e:
        print("\nERROR: %s: %s" % (type(e).__name__, e))
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        print("\nDisconnecting...")
        live_client.disconnect()
        paper_client.disconnect()
        print("Disconnected.")


if __name__ == "__main__":
    main()
