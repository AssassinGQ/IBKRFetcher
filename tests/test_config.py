"""UC-P1-12 through UC-P1-18: config load/save and symbols YAML."""

from pathlib import Path

import yaml

from ibkr_datafetcher.config import Config, load_symbols_from_yaml

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "configs" / "config.yaml"
DEFAULT_SYMBOLS = ROOT / "configs" / "symbols.yaml"


def test_uc_p1_12_config_from_default_file():
    cfg = Config.from_file(DEFAULT_CONFIG)
    assert cfg.gateway.host == "hgq-nas"
    assert cfg.gateway.port == 4004
    assert cfg.gateway.client_id == 1
    assert cfg.sync.retry_attempts == 3
    assert cfg.sync.retry_delay == 30
    assert cfg.database.path == "data/ibkr_cache.db"
    assert cfg.schedule.enabled is False
    assert cfg.schedule.cron == "0 9,16 * * *"


def test_uc_p1_13_config_roundtrip(tmp_path: Path):
    cfg = Config.from_file(DEFAULT_CONFIG)
    out = tmp_path / "out.yaml"
    cfg.to_file(out)
    again = Config.from_file(out)
    assert again == cfg


def test_uc_p1_14_load_symbols_from_default_yaml():
    symbols = load_symbols_from_yaml(DEFAULT_SYMBOLS)
    assert len(symbols) == 11
    assert symbols[0].symbol == "AAPL"
    assert symbols[0].name == "Apple Inc."


def test_uc_p1_15_minimal_yaml_uses_section_defaults(tmp_path: Path):
    path = tmp_path / "minimal.yaml"
    path.write_text("gateway:\n  host: localhost\n", encoding="utf-8")
    cfg = Config.from_file(path)
    assert cfg.gateway.host == "localhost"
    assert cfg.gateway.port == 4004
    assert cfg.sync.retry_attempts == 3


def test_uc_p1_16_hk_700_exchange_and_currency():
    symbols = load_symbols_from_yaml(DEFAULT_SYMBOLS)
    hk = next(s for s in symbols if s.symbol == "700")
    assert hk.exchange == "SEHK"
    assert hk.currency == "HKD"


def test_uc_p1_17_empty_symbols_yaml(tmp_path: Path):
    empty = tmp_path / "empty.yaml"
    empty.write_text("", encoding="utf-8")
    assert load_symbols_from_yaml(empty) == []


def test_uc_p1_18_partial_nested_overrides(tmp_path: Path):
    path = tmp_path / "partial.yaml"
    data = {
        "gateway": {"host": "g", "port": 5000},
        "sync": {"retry_attempts": 7},
        "database": {"path": "custom.db"},
        "schedule": {"enabled": True},
    }
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    cfg = Config.from_file(path)
    assert cfg.gateway.host == "g"
    assert cfg.gateway.port == 5000
    assert cfg.gateway.client_id == 1
    assert cfg.sync.retry_attempts == 7
    assert cfg.sync.retry_delay == 30
    assert cfg.database.path == "custom.db"
    assert cfg.schedule.enabled is True
    assert cfg.schedule.cron == "0 9,16 * * *"
