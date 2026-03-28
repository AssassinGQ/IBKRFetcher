import time
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from ibkr_datafetcher.config import GatewayConfig, SymbolConfig
from ibkr_datafetcher.ibkr_client import IBKRClient
from ibkr_datafetcher.types import Timeframe


class TestIBKRClientInit:
    def test_default_config(self):
        client = IBKRClient(GatewayConfig())
        assert client._config.host == "hgq-nas"
        assert client._config.port == 4004
        assert client._config.client_id == 1
        assert client._ib is None
        assert client._connected is False

    def test_custom_config(self):
        config = GatewayConfig(host="localhost", port=5000, client_id=99)
        client = IBKRClient(config)
        assert client._config.host == "localhost"
        assert client._config.port == 5000
        assert client._config.client_id == 99


class TestConnect:
    def test_is_connected_false_initially(self):
        client = IBKRClient(GatewayConfig())
        assert client.is_connected() is False

    @patch("ib_insync.IB")
    def test_connect_success(self, mock_ib_class):
        mock_ib = MagicMock()
        mock_ib.isConnected.return_value = True
        mock_ib_class.return_value = mock_ib

        client = IBKRClient(GatewayConfig())
        result = client.connect()

        assert result is True
        assert client._connected is True
        mock_ib.connect.assert_called_once()

    @patch("ib_insync.IB")
    def test_connect_already_connected(self, mock_ib_class):
        mock_ib = MagicMock()
        mock_ib.isConnected.return_value = True
        mock_ib_class.return_value = mock_ib

        client = IBKRClient(GatewayConfig())
        client.connect()
        client.connect()

        assert mock_ib.connect.call_count == 1

    @patch("ib_insync.IB")
    def test_connect_failure(self, mock_ib_class):
        mock_ib = MagicMock()
        mock_ib.connect.side_effect = ConnectionRefusedError()
        mock_ib_class.return_value = mock_ib

        client = IBKRClient(GatewayConfig())
        result = client.connect()

        assert result is False
        assert client._connected is False


class TestDisconnect:
    @patch("ib_insync.IB")
    def test_disconnect_when_connected(self, mock_ib_class):
        mock_ib = MagicMock()
        mock_ib.isConnected.return_value = True
        mock_ib_class.return_value = mock_ib

        client = IBKRClient(GatewayConfig())
        client.connect()
        client.disconnect()

        assert client._connected is False
        mock_ib.disconnect.assert_called_once()

    def test_disconnect_when_not_connected(self):
        client = IBKRClient(GatewayConfig())
        client.disconnect()

        assert client._connected is False
        assert client._ib is None


class TestReconnect:
    @patch("ib_insync.IB")
    def test_reconnect_success(self, mock_ib_class):
        mock_ib = MagicMock()
        mock_ib.isConnected.side_effect = [True, False, True]
        mock_ib_class.return_value = mock_ib

        client = IBKRClient(GatewayConfig())
        client.connect()
        result = client.reconnect(max_retries=3)

        assert result is True
        assert mock_ib.disconnect.call_count == 1
        assert mock_ib.connect.call_count == 2

    @patch("ib_insync.IB")
    @patch("time.sleep")
    def test_reconnect_failure(self, mock_sleep, mock_ib_class):
        mock_ib = MagicMock()
        mock_ib.isConnected.side_effect = [True, False, False]
        mock_ib.connect.side_effect = ConnectionRefusedError()
        mock_ib_class.return_value = mock_ib

        client = IBKRClient(GatewayConfig())
        client.connect()
        result = client.reconnect(max_retries=2)

        assert result is False


class TestMakeContract:
    def test_stock_contract(self):
        client = IBKRClient(GatewayConfig())
        config = SymbolConfig(symbol="AAPL", name="Apple", sec_type="STK", exchange="SMART", currency="USD")
        contract = client.make_contract(config)

        assert contract.symbol == "AAPL"
        assert contract.exchange == "SMART"
        assert contract.currency == "USD"

    def test_index_contract(self):
        client = IBKRClient(GatewayConfig())
        config = SymbolConfig(symbol="VIX", name="VIX", sec_type="IND", exchange="CBOE", currency="USD")
        contract = client.make_contract(config)

        assert contract.symbol == "VIX"
        assert contract.exchange == "CBOE"
        assert contract.currency == "USD"

    def test_future_contract(self):
        client = IBKRClient(GatewayConfig())
        config = SymbolConfig(symbol="ES", name="ES", sec_type="FUT", exchange="CME", currency="USD")
        contract = client.make_contract(config)

        assert contract.symbol == "ES"
        assert contract.exchange == "CME"
        assert contract.currency == "USD"
        assert contract.multiplier == ""

    def test_forex_contract(self):
        client = IBKRClient(GatewayConfig())
        config = SymbolConfig(symbol="EURUSD", name="EUR/USD", sec_type="CASH", exchange="IDEALPRO", currency="USD")
        contract = client.make_contract(config)

        assert contract.symbol == "EUR"
        assert contract.currency == "USD"
        assert contract.exchange == "IDEALPRO"

    def test_default_contract_is_stock(self):
        client = IBKRClient(GatewayConfig())
        config = SymbolConfig(symbol="TSLA", name="Tesla")
        contract = client.make_contract(config)

        assert contract.symbol == "TSLA"


class TestQualifyContract:
    @patch("ib_insync.IB")
    def test_qualify_contract_success(self, mock_ib_class):
        mock_ib = MagicMock()
        mock_ib.isConnected.return_value = True
        mock_ib.qualifyContracts.return_value = [MagicMock(conId=12345678)]
        mock_ib_class.return_value = mock_ib

        client = IBKRClient(GatewayConfig())
        client.connect()

        config = SymbolConfig(symbol="AAPL", name="Apple")
        contract = client.make_contract(config)
        con_id = client.qualify_contract(contract)

        assert con_id == 12345678

    @patch("ib_insync.IB")
    def test_qualify_contract_not_connected(self, mock_ib_class):
        mock_ib = MagicMock()
        mock_ib.isConnected.return_value = False
        mock_ib_class.return_value = mock_ib

        client = IBKRClient(GatewayConfig())
        client.connect()

        contract = MagicMock(symbol="AAPL")

        with pytest.raises(ConnectionError):
            client.qualify_contract(contract)

    @patch("ib_insync.IB")
    def test_qualify_contract_invalid(self, mock_ib_class):
        mock_ib = MagicMock()
        mock_ib.isConnected.return_value = True
        mock_ib.qualifyContracts.return_value = [MagicMock(conId=0)]
        mock_ib_class.return_value = mock_ib

        client = IBKRClient(GatewayConfig())
        client.connect()

        contract = MagicMock(symbol="INVALID")
        with pytest.raises(ValueError):
            client.qualify_contract(contract)


class TestGetHistoricalBars:
    @patch("ib_insync.IB")
    def test_get_historical_bars_success(self, mock_ib_class):
        mock_ib = MagicMock()
        mock_ib.isConnected.return_value = True
        mock_ib_class.return_value = mock_ib

        mock_bar = MagicMock()
        mock_bar.date = datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)
        mock_bar.open = 100.0
        mock_bar.high = 101.0
        mock_bar.low = 99.0
        mock_bar.close = 100.5
        mock_bar.volume = 1000000.0
        mock_bar.barCount = 100

        mock_ib.reqHistoricalData.return_value = [mock_bar]

        client = IBKRClient(GatewayConfig())
        client.connect()

        contract = MagicMock(symbol="AAPL")
        bars = client.get_historical_bars(contract, Timeframe.M1)

        assert len(bars) == 1
        assert bars[0].symbol == "AAPL"
        assert bars[0].timeframe == "1 min"
        assert bars[0].open == 100.0
        assert bars[0].high == 101.0
        assert bars[0].low == 99.0
        assert bars[0].close == 100.5

    @patch("ib_insync.IB")
    def test_get_historical_bars_not_connected(self, mock_ib_class):
        mock_ib = MagicMock()
        mock_ib.isConnected.return_value = False
        mock_ib_class.return_value = mock_ib

        client = IBKRClient(GatewayConfig())
        client.connect()

        contract = MagicMock(symbol="AAPL")

        with pytest.raises(ConnectionError):
            client.get_historical_bars(contract, Timeframe.M1)

    @patch("ib_insync.IB")
    def test_get_historical_bars_empty(self, mock_ib_class):
        mock_ib = MagicMock()
        mock_ib.isConnected.return_value = True
        mock_ib.reqHistoricalData.return_value = []
        mock_ib_class.return_value = mock_ib

        client = IBKRClient(GatewayConfig())
        client.connect()

        contract = MagicMock(symbol="AAPL")
        bars = client.get_historical_bars(contract, Timeframe.M1)

        assert len(bars) == 0

    @patch("ib_insync.IB")
    def test_get_historical_bars_with_end_time(self, mock_ib_class):
        mock_ib = MagicMock()
        mock_ib.isConnected.return_value = True
        mock_ib.reqHistoricalData.return_value = []
        mock_ib_class.return_value = mock_ib

        client = IBKRClient(GatewayConfig())
        client.connect()

        contract = MagicMock(symbol="AAPL")
        client.get_historical_bars(contract, Timeframe.M1, end_date_time="20240101 12:00:00")

        call_kwargs = mock_ib.reqHistoricalData.call_args[1]
        assert "endDateTime" in call_kwargs


class TestGetHistoricalNews:
    @patch("ib_insync.IB")
    def test_get_historical_news_success(self, mock_ib_class):
        mock_ib = MagicMock()
        mock_ib.isConnected.return_value = True
        mock_ib_class.return_value = mock_ib

        mock_news_item = MagicMock()
        mock_news_item.articleId = "BRFG$12345"
        mock_news_item.headline = "Test headline"
        mock_news_item.providerCode = "BRFG"
        mock_news_item.time = datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)

        mock_historical_news = MagicMock()
        mock_historical_news.news = [mock_news_item]
        mock_ib.reqHistoricalNews.return_value = mock_historical_news

        client = IBKRClient(GatewayConfig())
        client.connect()

        news = client.get_historical_news(con_id=12345678)

        assert len(news) == 1
        assert news[0].article_id == "BRFG$12345"
        assert news[0].headline == "Test headline"
        assert news[0].provider_code == "BRFG"

    @patch("ib_insync.IB")
    def test_get_historical_news_not_connected(self, mock_ib_class):
        mock_ib = MagicMock()
        mock_ib.isConnected.return_value = False
        mock_ib_class.return_value = mock_ib

        client = IBKRClient(GatewayConfig())
        client.connect()

        with pytest.raises(ConnectionError):
            client.get_historical_news(con_id=12345678)

    @patch("ib_insync.IB")
    def test_get_historical_news_empty(self, mock_ib_class):
        mock_ib = MagicMock()
        mock_ib.isConnected.return_value = True
        mock_ib.reqHistoricalNews.return_value = None
        mock_ib_class.return_value = mock_ib

        client = IBKRClient(GatewayConfig())
        client.connect()

        news = client.get_historical_news(con_id=12345678)

        assert len(news) == 0


class TestContractTypes:
    @pytest.mark.parametrize("sec_type,expected_type,test_symbol", [
        ("STK", "Stock", "AAPL"),
        ("IND", "Index", "VIX"),
        ("FUT", "Future", "ES"),
        ("CASH", "Forex", "EURUSD"),
    ])
    def test_contract_types(self, sec_type, expected_type, test_symbol):
        client = IBKRClient(GatewayConfig())
        config = SymbolConfig(symbol=test_symbol, name="Test", sec_type=sec_type, exchange="SMART", currency="USD")
        contract = client.make_contract(config)

        assert type(contract).__name__ == expected_type
