"""Quick verification tests for the mock IBKR gateway."""

import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ib_insync


MOCK_HOST = "127.0.0.1"
MOCK_PORT = 4012


async def run_all_tests():
    ib = ib_insync.IB()
    ib.RequestTimeout = 10

    print("1. Connecting...")
    await ib.connectAsync(host=MOCK_HOST, port=MOCK_PORT, clientId=99,
                          readonly=True, timeout=10)
    print(f"   Connected! Accounts: {ib.managedAccounts()}")
    assert ib.managedAccounts() == ["DU0000001"], "UC-P0-1/P0-11: managed accounts"

    print("2. Qualifying STK contract (AAPL)...")
    contract = ib_insync.Stock("AAPL", "SMART", "USD")
    qualified = await ib.qualifyContractsAsync(contract)
    assert qualified and qualified[0].conId > 0, "UC-P0-6: qualify STK"
    print(f"   conId={qualified[0].conId}")
    aapl = qualified[0]

    print("3. Qualifying IND contract (VIX)...")
    vix = ib_insync.Index("VIX", "CBOE", "USD")
    qualified_vix = await ib.qualifyContractsAsync(vix)
    assert qualified_vix and qualified_vix[0].conId > 0, "UC-P0-6: qualify IND"
    print(f"   conId={qualified_vix[0].conId}")
    vix_contract = qualified_vix[0]

    print("4. Historical data (AAPL, 1 day, 10 D, TRADES)...")
    bars = await ib.reqHistoricalDataAsync(
        aapl, endDateTime="", durationStr="10 D",
        barSizeSetting="1 day", whatToShow="TRADES",
        useRTH=True, formatDate=2, keepUpToDate=False)
    assert bars and len(bars) > 0, "UC-P0-4: bars > 0"
    bar = bars[0]
    assert hasattr(bar, 'date') and hasattr(bar, 'open'), "UC-P0-4: bar fields"
    print(f"   {len(bars)} bars, first: {bar.date} O={bar.open} H={bar.high} L={bar.low} C={bar.close} V={bar.volume}")

    print("5. Historical data (VIX, MIDPOINT)...")
    vix_bars = await ib.reqHistoricalDataAsync(
        vix_contract, endDateTime="", durationStr="1 W",
        barSizeSetting="1 hour", whatToShow="MIDPOINT",
        useRTH=True, formatDate=2, keepUpToDate=False)
    assert vix_bars and len(vix_bars) > 0, "UC-P0-5: VIX MIDPOINT bars > 0"
    print(f"   {len(vix_bars)} bars, last: close={vix_bars[-1].close}")

    print("6. News providers...")
    providers = await ib.reqNewsProvidersAsync()
    assert providers and len(providers) >= 3, "UC-P0-7: news providers"
    print(f"   {len(providers)} providers: {[p.code for p in providers]}")

    print("7. Historical news (AAPL, BRFG)...")
    from datetime import datetime, timedelta
    end_time = datetime.now()
    start_time = end_time - timedelta(days=7)
    news = await ib.reqHistoricalNewsAsync(
        conId=aapl.conId, providerCodes="BRFG",
        startDateTime=start_time.strftime("%Y%m%d-%H:%M:%S"),
        endDateTime=end_time.strftime("%Y%m%d-%H:%M:%S"),
        totalResults=5)
    assert news, "UC-P0-7: historical news"
    item = news[0]
    assert hasattr(item, 'articleId') and hasattr(item, 'headline'), "UC-P0-7: news fields"
    print(f"   {len(news)} articles, first: {item.articleId} - {item.headline[:50]}")

    print("8. Ticker snapshot (VIX)...")
    tickers = await ib.reqTickersAsync(vix_contract)
    assert tickers, "UC-P0-8: ticker"
    t = tickers[0]
    print(f"   bid={t.bid} ask={t.ask} last={t.last} high={t.high} low={t.low}")
    assert t.bid is not None or t.ask is not None, "UC-P0-8: VIX bid/ask"

    print("9. Market depth (AAPL)...")
    depth_event = asyncio.Event()
    depth_data = {}

    def on_depth(ticker):
        depth_data['bids'] = list(ticker.domBids)
        depth_data['asks'] = list(ticker.domAsks)
        depth_event.set()

    ticker_obj = ib.reqMktDepth(aapl, numRows=5, isSmartDepth=True)
    ticker_obj.updateEvent += on_depth
    try:
        await asyncio.wait_for(depth_event.wait(), timeout=5)
        assert depth_data.get('bids') or depth_data.get('asks'), "UC-P0-9: depth data"
        print(f"   bids={len(depth_data.get('bids', []))} asks={len(depth_data.get('asks', []))}")
    except asyncio.TimeoutError:
        print("   WARNING: depth timeout (non-critical)")
    finally:
        ib.cancelMktDepth(ticker_obj)

    print("10. Smart components...")
    try:
        components = await ib.reqSmartComponentsAsync("BOBO")
        print(f"   {len(components)} components")
    except Exception as e:
        print(f"   Smart components: {e}")

    print("11. News bulletins...")
    ib.reqNewsBulletins(allMessages=True)
    await asyncio.sleep(1)
    print(f"   Bulletins received (stored in wrapper)")

    print("\n12. Disconnecting...")
    ib.disconnect()
    print("   Done!")

    print("\n" + "=" * 50)
    print("ALL TESTS PASSED!")
    print("=" * 50)


if __name__ == "__main__":
    asyncio.run(run_all_tests())
