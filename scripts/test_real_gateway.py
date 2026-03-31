#!/usr/bin/env python3
"""Test fetching GOOGL data from a real IB Gateway at hgq-nas:4002."""
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

GW = GatewayConfig(host="hgq-nas", port=4002, client_id=88)


def main():
    client = IBKRClient(GW)

    print(f"Connecting to IB Gateway at {GW.host}:{GW.port}...")
    if not client.connect(timeout=60):
        print("FAILED to connect. Is IB Gateway running?")
        sys.exit(1)
    print("Connected!\n")

    try:
        # 1. Make and qualify contract
        print("=" * 60)
        print("1. Qualifying GOOGL contract...")
        contract = client.make_contract(GOOGL)
        print(f"   Contract created: {contract}")
        con_id = client.qualify_contract(contract)
        print(f"   Qualified! conId = {con_id}")
        print(f"   Full: symbol={contract.symbol}, exchange={contract.exchange}, "
              f"primary={contract.primaryExchange}, currency={contract.currency}")

        # 2. Fetch daily bars (last 5 days - small request)
        print("\n" + "=" * 60)
        print("2. Fetching daily bars (last 5 days)...")
        t0 = time.time()
        try:
            bars_d1 = client.get_historical_bars(
                contract, Timeframe.D1, duration="5 D", what_to_show="TRADES",
            )
            elapsed = time.time() - t0
            print(f"   Got {len(bars_d1)} daily bars in {elapsed:.1f}s")
            for b in bars_d1:
                print(f"   {b.bar_time.strftime('%Y-%m-%d')} O={b.open:.2f} "
                      f"H={b.high:.2f} L={b.low:.2f} C={b.close:.2f} V={b.volume:.0f}")
        except Exception as e:
            print(f"   FAILED: {e} (took {time.time()-t0:.1f}s)")
            print("   (Weekend/maintenance? Trying news instead...)")

        # 3. Fetch 1-hour bars (last 1 day)
        print("\n" + "=" * 60)
        print("3. Fetching 1-hour bars (last 1 day)...")
        t0 = time.time()
        try:
            bars_h1 = client.get_historical_bars(
                contract, Timeframe.H1, duration="1 D", what_to_show="TRADES",
            )
            elapsed = time.time() - t0
            print(f"   Got {len(bars_h1)} hourly bars in {elapsed:.1f}s")
            for b in bars_h1[:5]:
                print(f"   {b.bar_time.strftime('%Y-%m-%d %H:%M')} O={b.open:.2f} C={b.close:.2f} V={b.volume:.0f}")
        except Exception as e:
            print(f"   FAILED: {e} (took {time.time()-t0:.1f}s)")

        # 4. Fetch historical news
        print("\n" + "=" * 60)
        print(f"4. Fetching historical news for GOOGL (conId={con_id})...")
        t0 = time.time()
        try:
            news = client.get_historical_news(con_id, total_results=10)
            elapsed = time.time() - t0
            print(f"   Got {len(news)} news items in {elapsed:.1f}s")
            for i, n in enumerate(news[:5]):
                ts_str = time.strftime('%Y-%m-%d %H:%M', time.gmtime(n.timestamp))
                print(f"   [{i+1}] {ts_str} | {n.provider_code} | {n.headline[:70]}")
        except Exception as e:
            print(f"   FAILED: {e} (took {time.time()-t0:.1f}s)")

        print("\n" + "=" * 60)
        print("DONE!")

    except Exception as e:
        print(f"\nERROR: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        print("\nDisconnecting...")
        client.disconnect()
        print("Disconnected.")


if __name__ == "__main__":
    main()
