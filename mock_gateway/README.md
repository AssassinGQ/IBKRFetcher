# Mock IBKR Gateway

A mock TWS API server for local testing. Implements the TWS binary protocol that
`ib_insync` uses to communicate with IB Gateway/TWS.

## Quick Start

```bash
# From the project root:
python -m mock_gateway --port 4002

# Or directly:
python mock_gateway/ibkr_mock_server.py --port 4002
```

## Supported APIs

- `connectAsync` / `disconnect` — TCP handshake + API init
- `managedAccounts` — returns `["DU0000001"]`
- `qualifyContractsAsync` — returns contract with conId for known symbols
- `reqHistoricalDataAsync` — deterministic OHLCV bars
- `reqTickersAsync` — snapshot bid/ask/last/high/low
- `reqMktDepth` / `cancelMktDepth` — 5-level order book
- `reqNewsProvidersAsync` — BRFG, BRFUPDN, DJNL
- `reqNewsBulletins` — market advisories
- `reqHistoricalNewsAsync` — per-symbol historical news
- `reqSmartComponentsAsync` — exchange components

## Known Symbols

US Stocks: AAPL, SPY, MSFT, GOOGL
HK Stocks: 00700 / 700
Futures: ES
Volatility Indices: VIX, VIX3M, VIX9D, VXN, VXD, VXO, DX

## Testing

```bash
# Run the test scripts against the mock gateway:
python scripts/ibkr_kline_news_test.py --host 127.0.0.1 --port 4002 --symbols AAPL,SPY
python scripts/ibkr_vix_level2_test.py --host 127.0.0.1 --port 4002
```
