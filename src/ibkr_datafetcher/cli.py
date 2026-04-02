from __future__ import annotations

import csv
import io
import json
import os
import sys
from datetime import datetime, timezone
from typing import Optional

import click

from ibkr_datafetcher.config import Config, load_symbols_from_yaml
from ibkr_datafetcher.db import Database
from ibkr_datafetcher.ibkr_client import IBKRClient
from ibkr_datafetcher.kline_fetcher import KlineFetcher
from ibkr_datafetcher.news_fetcher import NewsFetcher
from ibkr_datafetcher.rate_limiter import RateLimiter
from ibkr_datafetcher.types import SymbolConfig, SyncProgress, Timeframe, resolve_timeframe

_DEFAULT_CONFIG = "configs/config.yaml"
_DEFAULT_SYMBOLS = "configs/symbols.yaml"


def _resolve_path(path: str) -> str:
    if os.path.isabs(path):
        return path
    return os.path.join(os.getcwd(), path)


def _load_config(config_path: str) -> Config:
    return Config.from_file(_resolve_path(config_path))


def _load_symbols(symbols_path: str) -> list[SymbolConfig]:
    return load_symbols_from_yaml(_resolve_path(symbols_path))


def _parse_symbol_list(raw: str, all_symbols: list[SymbolConfig]) -> list[SymbolConfig]:
    names = {s.strip().upper() for s in raw.split(",")}
    matched = [sc for sc in all_symbols if sc.symbol.upper() in names]
    return matched


def _parse_timeframes(raw: str) -> list[Timeframe]:
    out: list[Timeframe] = []
    for part in raw.split(","):
        tf = resolve_timeframe(part)
        if tf is not None:
            out.append(tf)
    return out


def _format_elapsed(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def _progress_printer(prog: SyncProgress) -> None:
    stats = prog.rate_limiter_stats
    util_pct = stats.get("utilization", 0.0) * 100
    hist_n = stats.get("hist_requests", 0)
    news_n = stats.get("news_requests", 0)
    waits = stats.get("total_waits", 0)

    pct = (prog.current_range / prog.total_ranges * 100) if prog.total_ranges else 0
    pbar_len = 20
    filled = int(pbar_len * pct / 100)
    pbar = "\u2588" * filled + "\u2591" * (pbar_len - filled)

    elapsed_str = _format_elapsed(prog.elapsed_sec)
    eta_str = _format_elapsed(prog.eta_sec) if prog.eta_sec is not None else "N/A"

    click.echo(
        f"\r  [{prog.symbol}/{prog.timeframe.value}] "
        f"{prog.current_range}/{prog.total_ranges} "
        f"{pbar} {pct:.0f}% ({prog.bars_fetched} bars) "
        f"| {elapsed_str} / ~{eta_str} "
        f"| rate: hist={hist_n} news={news_n} util={util_pct:.0f}% waits={waits}",
        nl=False,
    )


@click.group(
    context_settings={"help_option_names": ["-h", "--help"]},
    invoke_without_command=True,
)
@click.pass_context
def main(ctx: click.Context) -> None:
    """IBKR K-line data sync tool"""
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


@main.command()
@click.option("--symbols", default=None, help="Comma-separated symbol list")
@click.option("--timeframes", default=None,
              help="Comma-separated timeframes, e.g. D1,H1,M5 (aliases: 1D,1H,5M). "
                   "Omit to sync all timeframes.")
@click.option("--config", "config_path", default=_DEFAULT_CONFIG)
@click.option("--symbols-config", default=_DEFAULT_SYMBOLS)
def sync(symbols, timeframes, config_path, symbols_config):
    """Sync K-line data from IBKR"""
    cfg = _load_config(config_path)
    all_syms = _load_symbols(symbols_config)

    syms = _parse_symbol_list(symbols, all_syms) if symbols else all_syms
    tfs = _parse_timeframes(timeframes) if timeframes else None

    if not syms:
        click.echo("No matching symbols found.")
        return

    db = Database(cfg.database.path)
    kline_client = IBKRClient(cfg.gateway)
    rl = RateLimiter()

    news_gw = cfg.news_gateway if cfg.news_gateway else cfg.gateway
    news_client = IBKRClient(news_gw) if cfg.news_gateway else kline_client

    click.echo(f"Connecting to IBKR Gateway (kline) at {cfg.gateway.host}:{cfg.gateway.port}...")
    if not kline_client.connect():
        click.echo("Failed to connect to kline gateway.", err=True)
        db.close()
        sys.exit(1)

    if cfg.news_gateway:
        click.echo(f"Connecting to IBKR Gateway (news) at {news_gw.host}:{news_gw.port}...")
        if not news_client.connect():
            click.echo("Failed to connect to news gateway.", err=True)
            kline_client.disconnect()
            db.close()
            sys.exit(1)

    fetcher = KlineFetcher(kline_client, rl, db)
    news_fetcher = NewsFetcher(news_client, rl, db)

    try:
        click.echo(f"Syncing klines for {len(syms)} symbol(s)...")
        result = fetcher.sync_all(syms, timeframes=tfs, progress_callback=_progress_printer)
        click.echo("")
        click.echo(
            f"Klines: {result['total_bars']} bars fetched, "
            f"{result['symbols_processed']} tasks processed, "
            f"{len(result['errors'])} errors."
        )
        for err in result["errors"]:
            click.echo(f"  ERROR: {err}", err=True)

        click.echo(f"\nSyncing news for {len(syms)} symbol(s)...")
        for sc in syms:
            try:
                nr = news_fetcher.fetch_symbol_news(sc)
                click.echo(f"  {sc.symbol}: {nr['news_count']} articles")
            except (ConnectionError, ValueError, OSError) as e:
                click.echo(f"  {sc.symbol}: news error: {e}", err=True)
    finally:
        kline_client.disconnect()
        if cfg.news_gateway:
            news_client.disconnect()
        db.close()


def _resolve_timeframe_name(timeframe: str) -> str | None:
    tf = resolve_timeframe(timeframe)
    return tf.name if tf else None


def _format_bars(bars: list, fmt: str) -> str:
    if fmt == "json":
        data = [
            {"symbol": b.symbol, "timeframe": b.timeframe.name, "timestamp": b.timestamp,
             "open": b.open, "high": b.high, "low": b.low, "close": b.close,
             "volume": b.volume, "bar_count": b.bar_count,
             "bar_time": b.bar_time.isoformat()}
            for b in bars
        ]
        return json.dumps(data, indent=2)
    if fmt == "csv":
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["symbol", "timeframe", "timestamp", "open", "high",
                         "low", "close", "volume", "bar_count", "bar_time"])
        for b in bars:
            writer.writerow([b.symbol, b.timeframe.name, b.timestamp,
                             b.open, b.high, b.low, b.close, b.volume,
                             b.bar_count, b.bar_time.isoformat()])
        return buf.getvalue()
    if not bars:
        return "No data found."
    header = (f"{'Symbol':<8} {'TF':<8} {'Timestamp':<12} {'Open':>10} "
              f"{'High':>10} {'Low':>10} {'Close':>10} {'Volume':>12} {'Count':>6} {'BarTime'}")
    lines = [header, "-" * len(header)]
    for b in bars:
        lines.append(
            f"{b.symbol:<8} {b.timeframe.name:<8} {b.timestamp:<12} "
            f"{b.open:>10.2f} {b.high:>10.2f} {b.low:>10.2f} {b.close:>10.2f} "
            f"{b.volume:>12.0f} {b.bar_count:>6} {b.bar_time.isoformat()}"
        )
    return "\n".join(lines)


def _format_time_range(earliest: Optional[int], latest: Optional[int], timeframe: Timeframe) -> str:
    if earliest is None or latest is None:
        return "No data found."

    earliest_dt = datetime.fromtimestamp(earliest, tz=timezone.utc)
    latest_dt = datetime.fromtimestamp(latest, tz=timezone.utc)

    is_second = timeframe in (Timeframe.S5, Timeframe.S10, Timeframe.S15, Timeframe.S30)
    is_minute = timeframe in (Timeframe.M1, Timeframe.M2, Timeframe.M3, Timeframe.M5,
                              Timeframe.M10, Timeframe.M15, Timeframe.M20, Timeframe.M30)
    is_hour = timeframe in (Timeframe.H1, Timeframe.H2, Timeframe.H3, Timeframe.H4, Timeframe.H8)
    is_day = timeframe == Timeframe.D1
    is_week = timeframe == Timeframe.W1
    is_month = timeframe == Timeframe.MN1

    if is_second:
        return f"{earliest_dt.strftime('%Y-%m-%d %H:%M:%S')} ~ {latest_dt.strftime('%Y-%m-%d %H:%M:%S')}"
    if is_minute:
        return f"{earliest_dt.strftime('%Y-%m-%d %H:%M')} ~ {latest_dt.strftime('%Y-%m-%d %H:%M')}"
    if is_hour:
        return f"{earliest_dt.strftime('%Y-%m-%d %H:00')} ~ {latest_dt.strftime('%Y-%m-%d %H:00')}"
    if is_week:
        return f"{earliest_dt.strftime('%Y-%m-%d')} ~ {latest_dt.strftime('%Y-%m-%d')}"
    if is_month:
        return f"{earliest_dt.strftime('%Y-%m')} ~ {latest_dt.strftime('%Y-%m')}"
    return f"{earliest_dt.strftime('%Y-%m-%d')} ~ {latest_dt.strftime('%Y-%m-%d')}"


@main.command()
@click.argument("symbol")
@click.option("--timeframe", default=None, help="Bar size, e.g. '1 day' (optional)")
@click.option("--config", "config_path", default=_DEFAULT_CONFIG)
def query(symbol, timeframe, config_path):  # pylint: disable=too-many-branches
    """Query time range of local K-line data"""
    cfg = _load_config(config_path)
    db = Database(cfg.database.path)

    try:
        if timeframe:
            tf_name = _resolve_timeframe_name(timeframe)
            if tf_name is None:
                click.echo(f"Unknown timeframe: {timeframe}", err=True)
                sys.exit(1)

            earliest, latest = db.get_time_range(symbol.upper(), tf_name)
            if earliest is None or latest is None:
                click.echo("No data found.")
            else:
                tf = Timeframe[tf_name]
                text = _format_time_range(earliest, latest, tf)
                click.echo(text)
        else:
            tf_names = db.get_timeframes_for_symbol(symbol.upper())
            if not tf_names:
                click.echo("No data found.")
            else:
                for tf_name in tf_names:
                    earliest, latest = db.get_time_range(symbol.upper(), tf_name)
                    if earliest is not None and latest is not None:
                        tf = Timeframe[tf_name]
                        text = _format_time_range(earliest, latest, tf)
                        click.echo(f"{tf_name}: {text}")
    finally:
        db.close()


@main.command()
@click.option("--symbol", default=None, help="Filter by symbol")
@click.option("--config", "config_path", default=_DEFAULT_CONFIG)
def status(symbol, config_path):
    """View sync status"""
    cfg = _load_config(config_path)
    db = Database(cfg.database.path)

    try:
        if symbol:
            rows: list = db.get_sync_status(symbol.upper())
        else:
            rows = list(db.get_all_sync_status())
    finally:
        db.close()

    if not rows:
        click.echo("No sync status found.")
        return

    header = f"{'Symbol':<10} {'Timeframe':<10} {'LatestBar':>12} {'Bars':>8} {'SyncedAt'}"
    click.echo(header)
    click.echo("-" * len(header))
    for r in rows:
        click.echo(
            f"{r.symbol:<10} {r.timeframe.name:<10} {r.latest_bar_time:>12} "
            f"{r.bar_count:>8} {r.synced_at.isoformat()}"
        )


@main.command()
@click.option("--symbols", required=True, help="Comma-separated symbol list")
@click.option("--days", default=30, type=int, help="Days of news to fetch")
@click.option("--config", "config_path", default=_DEFAULT_CONFIG)
@click.option("--symbols-config", default=_DEFAULT_SYMBOLS)
def news(symbols, days, config_path, symbols_config):
    """Fetch news data from IBKR"""
    cfg = _load_config(config_path)
    all_syms = _load_symbols(symbols_config)
    syms = _parse_symbol_list(symbols, all_syms)

    if not syms:
        click.echo("No matching symbols found.")
        return

    news_gw = cfg.news_gateway if cfg.news_gateway else cfg.gateway
    db = Database(cfg.database.path)
    client = IBKRClient(news_gw)
    rl = RateLimiter()
    fetcher = NewsFetcher(client, rl, db)

    click.echo(f"Connecting to IBKR Gateway (news) at {news_gw.host}:{news_gw.port}...")
    if not client.connect():
        click.echo("Failed to connect.", err=True)
        db.close()
        sys.exit(1)

    try:
        for sc in syms:
            click.echo(f"Fetching news for {sc.symbol}...")
            result = fetcher.fetch_symbol_news(sc, days=days)
            click.echo(f"  {result['news_count']} articles fetched.")
    finally:
        client.disconnect()
        db.close()


@main.command()
@click.option("--schedule", required=True, help="Cron expression, e.g. '0 9,16 * * *'")
@click.option("--config", "config_path", default=_DEFAULT_CONFIG)
@click.option("--symbols-config", default=_DEFAULT_SYMBOLS)
def serve(schedule, config_path, symbols_config):
    """Start scheduled sync service"""
    cfg = _load_config(config_path)
    all_syms = _load_symbols(symbols_config)

    db = Database(cfg.database.path)
    kline_client = IBKRClient(cfg.gateway)
    rl = RateLimiter()

    news_gw = cfg.news_gateway if cfg.news_gateway else cfg.gateway
    news_client = IBKRClient(news_gw) if cfg.news_gateway else kline_client

    click.echo(f"Connecting to IBKR Gateway (kline) at {cfg.gateway.host}:{cfg.gateway.port}...")
    if not kline_client.connect():
        click.echo("Failed to connect to kline gateway.", err=True)
        db.close()
        sys.exit(1)

    if cfg.news_gateway:
        click.echo(f"Connecting to IBKR Gateway (news) at {news_gw.host}:{news_gw.port}...")
        if not news_client.connect():
            click.echo("Failed to connect to news gateway.", err=True)
            kline_client.disconnect()
            db.close()
            sys.exit(1)

    fetcher = KlineFetcher(kline_client, rl, db)

    try:
        from ibkr_datafetcher.scheduler import Scheduler  # pylint: disable=import-outside-toplevel
        sched = Scheduler(fetcher, all_syms)
        click.echo(f"Starting scheduler with cron: {schedule}")
        sched.start(schedule)
    except KeyboardInterrupt:
        click.echo("\nStopping...")
    finally:
        kline_client.disconnect()
        if cfg.news_gateway:
            news_client.disconnect()
        db.close()


@main.command(name="reconnect")
@click.option("--config", "config_path", default=_DEFAULT_CONFIG)
def reconnect_cmd(config_path):
    """Check/reconnect IBKR Gateway(s)"""
    cfg = _load_config(config_path)

    kline_client = IBKRClient(cfg.gateway)
    click.echo(f"Kline gateway ({cfg.gateway.host}:{cfg.gateway.port})...")
    if kline_client.connect():
        click.echo("  Connected.")
    else:
        click.echo("  FAILED.", err=True)
    kline_client.disconnect()

    if cfg.news_gateway:
        news_client = IBKRClient(cfg.news_gateway)
        click.echo(f"News gateway ({cfg.news_gateway.host}:{cfg.news_gateway.port})...")
        if news_client.connect():
            click.echo("  Connected.")
        else:
            click.echo("  FAILED.", err=True)
        news_client.disconnect()


if __name__ == "__main__":
    main()  # pylint: disable=no-value-for-parameter
