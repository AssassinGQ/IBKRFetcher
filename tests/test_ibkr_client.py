"""UC-P4-1 through UC-P4-26: IBKRClient against mock gateway."""

from datetime import datetime, timedelta

import pytest
from ib_insync import Index, Stock

from ibkr_datafetcher.config import GatewayConfig
from ibkr_datafetcher.ibkr_client import IBKRClient
from ibkr_datafetcher.types import SymbolConfig, Timeframe


@pytest.fixture
def gw_cfg(mock_gateway_port):
    return GatewayConfig(host="127.0.0.1", port=mock_gateway_port, client_id=11)


def test_uc_p4_1_construct_without_connecting(gw_cfg):
    c = IBKRClient(gw_cfg)
    assert not c.is_connected()


def test_uc_p4_2_connect_succeeds(gw_cfg):
    c = IBKRClient(gw_cfg)
    assert c.connect() is True
    assert c.is_connected()
    c.disconnect()


def test_uc_p4_3_connect_timeout_bad_port():
    cfg = GatewayConfig(host="127.0.0.1", port=19999, client_id=12)
    c = IBKRClient(cfg)
    assert c.connect(timeout=5) is False


def test_uc_p4_4_disconnect(gw_cfg):
    c = IBKRClient(gw_cfg)
    assert c.connect()
    c.disconnect()
    assert not c.is_connected()


def test_uc_p4_5_after_disconnect_thread_stopped(gw_cfg):
    c = IBKRClient(gw_cfg)
    assert c.connect()
    thread = c._thread
    assert thread is not None
    assert thread.is_alive()
    c.disconnect()
    assert not thread.is_alive()


def test_uc_p4_6_reconnect_after_disconnect(gw_cfg):
    c = IBKRClient(gw_cfg)
    assert c.connect()
    c.disconnect()
    assert c.reconnect(max_retries=3) is True
    assert c.is_connected()
    c.disconnect()


def test_uc_p4_7_reconnect_max_retries_one_bad_port():
    cfg = GatewayConfig(host="127.0.0.1", port=19999, client_id=13)
    c = IBKRClient(cfg)
    assert c.reconnect(max_retries=1) is False


def test_uc_p4_8_make_contract_stk_aapl(gw_cfg):
    c = IBKRClient(gw_cfg)
    sc = SymbolConfig(symbol="AAPL", name="Apple", sec_type="STK", exchange="SMART", currency="USD")
    ct = c.make_contract(sc)
    assert ct.secType == "STK"
    assert ct.symbol == "AAPL"


def test_uc_p4_9_make_contract_stk_hk_700(gw_cfg):
    c = IBKRClient(gw_cfg)
    sc = SymbolConfig(symbol="700", name="Tencent", sec_type="STK", exchange="SEHK", currency="HKD")
    ct = c.make_contract(sc)
    assert ct.secType == "STK"
    assert ct.symbol == "700"
    assert ct.currency == "HKD"


def test_uc_p4_10_make_contract_fut(gw_cfg):
    c = IBKRClient(gw_cfg)
    sc = SymbolConfig(symbol="ES", name="ES", sec_type="FUT", exchange="GLOBEX", currency="USD")
    ct = c.make_contract(sc)
    assert ct.secType == "FUT"
    assert ct.symbol == "ES"


def test_uc_p4_11_make_contract_cash(gw_cfg):
    c = IBKRClient(gw_cfg)
    sc = SymbolConfig(symbol="EUR", name="EURUSD", sec_type="CASH", exchange="IDEALPRO", currency="USD")
    ct = c.make_contract(sc)
    assert ct.secType == "CASH"
    assert ct.symbol == "EUR"


def test_uc_p4_12_make_contract_ind_vix(gw_cfg):
    c = IBKRClient(gw_cfg)
    sc = SymbolConfig(symbol="VIX", name="VIX", sec_type="IND", exchange="CBOE", currency="USD")
    ct = c.make_contract(sc)
    assert ct.secType == "IND"
    assert ct.symbol == "VIX"


def test_uc_p4_13_qualify_stk_conid_positive(gw_cfg):
    c = IBKRClient(gw_cfg)
    assert c.connect()
    ct = Stock("AAPL", "SMART", "USD")
    cid = c.qualify_contract(ct)
    assert cid > 0
    c.disconnect()


def test_uc_p4_14_qualify_ind_vix_conid_positive(gw_cfg):
    c = IBKRClient(gw_cfg)
    assert c.connect()
    ct = Index("VIX", "CBOE", "USD")
    cid = c.qualify_contract(ct)
    assert cid > 0
    c.disconnect()


def test_uc_p4_15_qualify_invalid_raises(gw_cfg):
    c = IBKRClient(gw_cfg)
    assert c.connect()
    ct = Stock("ZZZZZ", "SMART", "USD")
    with pytest.raises(ValueError, match="contract not found"):
        c.qualify_contract(ct)
    c.disconnect()


def test_uc_p4_16_historical_bars_nonempty(gw_cfg):
    c = IBKRClient(gw_cfg)
    assert c.connect()
    ct = Stock("AAPL", "SMART", "USD")
    c.qualify_contract(ct)
    bars = c.get_historical_bars(ct, Timeframe.D1)
    assert len(bars) > 0
    c.disconnect()


def test_uc_p4_17_klinebar_all_fields(gw_cfg):
    c = IBKRClient(gw_cfg)
    assert c.connect()
    ct = Stock("AAPL", "SMART", "USD")
    c.qualify_contract(ct)
    bars = c.get_historical_bars(ct, Timeframe.D1, duration="3 D")
    assert bars
    b = bars[0]
    assert b.symbol
    assert b.timeframe == Timeframe.D1
    assert isinstance(b.timestamp, int) and b.timestamp > 0
    assert isinstance(b.open, float)
    assert isinstance(b.high, float)
    assert isinstance(b.low, float)
    assert isinstance(b.close, float)
    assert isinstance(b.volume, float)
    assert isinstance(b.bar_count, int)
    assert isinstance(b.bar_time, datetime)
    c.disconnect()


def test_uc_p4_18_end_date_time_param(gw_cfg):
    c = IBKRClient(gw_cfg)
    assert c.connect()
    ct = Stock("SPY", "SMART", "USD")
    c.qualify_contract(ct)
    end = datetime.now().strftime("%Y%m%d %H:%M:%S")
    bars = c.get_historical_bars(ct, Timeframe.D1, end_date_time=end, duration="5 D")
    assert len(bars) == 5
    c.disconnect()


def test_uc_p4_19_duration_param(gw_cfg):
    c = IBKRClient(gw_cfg)
    assert c.connect()
    ct = Stock("MSFT", "SMART", "USD")
    c.qualify_contract(ct)
    bars = c.get_historical_bars(ct, Timeframe.M5, duration="1 D")
    assert len(bars) > 0
    c.disconnect()


def test_uc_p4_20_vix_midpoint(gw_cfg):
    c = IBKRClient(gw_cfg)
    assert c.connect()
    ct = Index("VIX", "CBOE", "USD")
    c.qualify_contract(ct)
    bars = c.get_historical_bars(
        ct, Timeframe.H1, duration="1 W", what_to_show="MIDPOINT"
    )
    assert len(bars) > 0
    c.disconnect()


def test_uc_p4_21_very_early_end_returns_empty(gw_cfg):
    c = IBKRClient(gw_cfg)
    assert c.connect()
    ct = Stock("AAPL", "SMART", "USD")
    c.qualify_contract(ct)
    bars = c.get_historical_bars(
        ct, Timeframe.D1, end_date_time="19000101 12:00:00", duration="10 D"
    )
    assert bars == []
    c.disconnect()


def test_uc_p4_22_historical_not_connected_raises(gw_cfg):
    c = IBKRClient(gw_cfg)
    ct = Stock("AAPL", "SMART", "USD")
    with pytest.raises(ConnectionError):
        c.get_historical_bars(ct, Timeframe.D1)


def test_uc_p4_23_historical_news_nonempty(gw_cfg):
    c = IBKRClient(gw_cfg)
    assert c.connect()
    ct = Stock("AAPL", "SMART", "USD")
    c.qualify_contract(ct)
    end = datetime.now()
    start = end - timedelta(days=7)
    news = c.get_historical_news(
        ct.conId,
        provider_codes="BRFG",
        start_time=start.strftime("%Y%m%d-%H:%M:%S"),
        end_time=end.strftime("%Y%m%d-%H:%M:%S"),
        total_results=5,
    )
    assert len(news) > 0
    c.disconnect()


def test_uc_p4_24_news_item_fields(gw_cfg):
    c = IBKRClient(gw_cfg)
    assert c.connect()
    ct = Stock("AAPL", "SMART", "USD")
    c.qualify_contract(ct)
    end = datetime.now()
    start = end - timedelta(days=7)
    news = c.get_historical_news(
        ct.conId,
        start_time=start.strftime("%Y%m%d-%H:%M:%S"),
        end_time=end.strftime("%Y%m%d-%H:%M:%S"),
        total_results=3,
    )
    for n in news:
        assert n.article_id
        assert n.headline
    c.disconnect()


def test_uc_p4_25_news_bad_conid_empty(gw_cfg):
    c = IBKRClient(gw_cfg)
    assert c.connect()
    assert c.get_historical_news(0) == []
    c.disconnect()


def test_uc_p4_26_news_not_connected_raises(gw_cfg):
    c = IBKRClient(gw_cfg)
    with pytest.raises(ConnectionError):
        c.get_historical_news(265598)
