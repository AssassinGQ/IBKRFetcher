from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .types import SymbolConfig


@dataclass
class GatewayConfig:
    host: str = "hgq-nas"
    port: int = 4004
    client_id: int = 1


@dataclass
class SyncConfig:
    retry_attempts: int = 3
    retry_delay: int = 30
    symbols: list = field(default_factory=list)


@dataclass
class DatabaseConfig:
    path: str = "data/ibkr_cache.db"


@dataclass
class ScheduleConfig:
    enabled: bool = False
    cron: str = "0 9,16 * * *"


@dataclass
class Config:
    gateway: GatewayConfig = field(default_factory=GatewayConfig)
    sync: SyncConfig = field(default_factory=SyncConfig)
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    schedule: ScheduleConfig = field(default_factory=ScheduleConfig)

    @classmethod
    def from_file(cls, path: str) -> "Config":
        path_obj = Path(path)
        if not path_obj.exists():
            raise FileNotFoundError(f"Config file not found: {path}")

        with open(path_obj, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        gateway_data = data.get("gateway", {})
        sync_data = data.get("sync", {})
        database_data = data.get("database", {})
        schedule_data = data.get("schedule", {})

        gateway = GatewayConfig(**gateway_data) if gateway_data else GatewayConfig()
        sync = SyncConfig(**sync_data) if sync_data else SyncConfig()
        database = DatabaseConfig(**database_data) if database_data else DatabaseConfig()
        schedule = ScheduleConfig(**schedule_data) if schedule_data else ScheduleConfig()

        return cls(gateway=gateway, sync=sync, database=database, schedule=schedule)

    def to_file(self, path: str) -> None:
        path_obj = Path(path)
        path_obj.parent.mkdir(parents=True, exist_ok=True)

        data = {
            "gateway": {
                "host": self.gateway.host,
                "port": self.gateway.port,
                "client_id": self.gateway.client_id,
            },
            "sync": {
                "retry_attempts": self.sync.retry_attempts,
                "retry_delay": self.sync.retry_delay,
            },
            "database": {
                "path": self.database.path,
            },
            "schedule": {
                "enabled": self.schedule.enabled,
                "cron": self.schedule.cron,
            },
        }

        with open(path_obj, "w", encoding="utf-8") as f:
            yaml.dump(data, f, default_flow_style=False, allow_unicode=True)


def load_symbols_from_yaml(path: str) -> list[SymbolConfig]:
    path_obj = Path(path)
    if not path_obj.exists():
        raise FileNotFoundError(f"Symbols file not found: {path}")

    with open(path_obj, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    symbols = []
    for item in data.get("symbols", []):
        symbols.append(SymbolConfig(**item))

    return symbols


def load_config(config_path: str) -> Config:
    cfg = Config.from_file(config_path)

    symbols_path = "configs/symbols.yaml"
    if Path(symbols_path).exists():
        cfg.sync.symbols = load_symbols_from_yaml(symbols_path)
    else:
        cfg.sync.symbols = []

    return cfg
