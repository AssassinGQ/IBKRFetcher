from __future__ import annotations

import logging
import time

from ibkr_datafetcher.db import Database
from ibkr_datafetcher.ibkr_client import IBKRClient
from ibkr_datafetcher.rate_limiter import RateLimiter
from ibkr_datafetcher.timeframe_prober import NewsProber
from ibkr_datafetcher.types import NewsItem, SymbolConfig

logger = logging.getLogger(__name__)


class NewsFetcher:
    def __init__(self, client: IBKRClient, rate_limiter: RateLimiter, db: Database):
        self._client = client
        self._rate_limiter = rate_limiter
        self._db = db
        self._prober = NewsProber(client, rate_limiter, db)

    def fetch_symbol_news(
        self,
        symbol_config: SymbolConfig,
        days: int = 30,
        provider_codes: str = "BRFG+BRFUPDN+DJNL",
    ) -> dict:
        sym = symbol_config.symbol
        contract = self._client.make_contract(symbol_config)
        con_id = self._client.qualify_contract(contract)

        ranges = self._prober.get_pending_ranges(symbol_config, days=days)
        if not ranges:
            return {"symbol": sym, "news_count": 0}

        total_count = 0
        for tr in ranges:
            start_str = tr.start_time.strftime("%Y-%m-%d %H:%M:%S.0")
            end_str = tr.end_time.strftime("%Y-%m-%d %H:%M:%S.0")

            self._rate_limiter.acquire(
                request_type="news",
                symbol=sym,
                exchange=symbol_config.exchange,
                sec_type=symbol_config.sec_type,
            )
            items = self._client.get_historical_news(
                con_id, provider_codes,
                start_time=start_str,
                end_time=end_str,
            )
            tagged: list[NewsItem] = []
            for item in items:
                tagged.append(NewsItem(
                    article_id=item.article_id,
                    symbol=sym,
                    headline=item.headline,
                    provider_code=item.provider_code,
                    timestamp=item.timestamp,
                ))
            if tagged:
                self._db.insert_news(tagged)
                total_count += len(tagged)

        time.sleep(0.05)
        return {"symbol": sym, "news_count": total_count}
