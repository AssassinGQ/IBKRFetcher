from __future__ import annotations

import dataclasses
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any, TypeVar, cast

import yaml

from ibkr_datafetcher.types import SymbolConfig

T = TypeVar("T")


def _mapping_to_dataclass(cls: type[T], section: dict[str, Any] | None) -> T:
    data = section or {}
    kwargs: dict[str, Any] = {}
    for f in fields(cls):
        if f.name in data:
            kwargs[f.name] = data[f.name]
        elif f.default is not dataclasses.MISSING:
            kwargs[f.name] = f.default
        elif f.default_factory is not dataclasses.MISSING:
            kwargs[f.name] = f.default_factory()
        else:
            msg = f"missing required key {f.name!r}"
            raise ValueError(msg)
    return cls(**kwargs)


@dataclass
class GatewayConfig:
    host: str = "hgq-nas"
    port: int = 4004
    client_id: int = 1


@dataclass
class SyncConfig:
    retry_attempts: int = 3
    retry_delay: int = 30


@dataclass
class DatabaseConfig:
    path: str = "data/ibkr_cache.db"


@dataclass
class ScheduleConfig:
    enabled: bool = False
    cron: str = "0 9,16 * * *"


@dataclass
class Config:
    gateway: GatewayConfig
    sync: SyncConfig
    database: DatabaseConfig
    schedule: ScheduleConfig

    @classmethod
    def from_file(cls, path: str | Path) -> Config:
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            msg = "config root must be a mapping"
            raise ValueError(msg)
        data = cast(dict[str, Any], raw)
        gw = cast(dict[str, Any] | None, data.get("gateway"))
        sy = cast(dict[str, Any] | None, data.get("sync"))
        db = cast(dict[str, Any] | None, data.get("database"))
        sc = cast(dict[str, Any] | None, data.get("schedule"))
        return cls(
            gateway=_mapping_to_dataclass(GatewayConfig, gw),
            sync=_mapping_to_dataclass(SyncConfig, sy),
            database=_mapping_to_dataclass(DatabaseConfig, db),
            schedule=_mapping_to_dataclass(ScheduleConfig, sc),
        )

    def to_file(self, path: str | Path) -> None:
        payload = {
            "gateway": asdict(self.gateway),
            "sync": asdict(self.sync),
            "database": asdict(self.database),
            "schedule": asdict(self.schedule),
        }
        Path(path).write_text(
            yaml.safe_dump(payload, default_flow_style=False, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )


def load_symbols_from_yaml(path: str | Path) -> list[SymbolConfig]:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if raw is None:
        return []
    if not isinstance(raw, list):
        msg = "symbols file must be a list of symbol entries"
        raise ValueError(msg)
    out: list[SymbolConfig] = []
    for item in raw:
        if not isinstance(item, dict):
            msg = "each symbol entry must be a mapping"
            raise ValueError(msg)
        row = cast(dict[str, Any], item)
        out.append(_mapping_to_dataclass(SymbolConfig, row))
    return out
