from ibkr_datafetcher.config import SymbolConfig
from ibkr_datafetcher.db import Database
from ibkr_datafetcher.ibkr_client import IBKRClient
from ibkr_datafetcher.rate_limiter import RateLimiter
from ibkr_datafetcher.timeframe_prober import NewsProber


class NewsFetcher:
    def __init__(
        self,
        ibkr_client: IBKRClient,
        rate_limiter: RateLimiter,
        db: Database,
    ):
        self._client = ibkr_client
        self._rate_limiter = rate_limiter
        self._db = db
        self._prober = NewsProber(ibkr_client, rate_limiter, db)

    def fetch_symbol_news(
        self,
        symbol_config: SymbolConfig,
        days: int = 30,
        provider_codes: str = "BRFG+BRFUPDN+DJNL",
    ) -> dict:
        news_count = 0
        errors = []
        _ = days

        try:
            contract = self._client.make_contract(symbol_config)
            con_id = self._client.qualify_contract(contract)
        except Exception as e:
            return {
                "symbol": symbol_config.symbol,
                "news_count": 0,
                "errors": [str(e)],
            }

        if con_id == 0:
            return {
                "symbol": symbol_config.symbol,
                "news_count": 0,
                "errors": ["Contract not qualified"],
            }

        try:
            self._rate_limiter.acquire("news", symbol_config.symbol)
            news_list = self._client.get_historical_news(
                con_id=con_id,
                provider_codes=provider_codes,
                start_time=None,
                end_time=None,
                total_results=100,
            )

            for news in news_list:
                self._db.write_news(news)
                news_count += 1

        except Exception as e:
            errors.append(str(e))

        return {
            "symbol": symbol_config.symbol,
            "news_count": news_count,
            "errors": errors,
        }
