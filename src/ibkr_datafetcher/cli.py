import json as _json
import sys
import time
from datetime import datetime
from pathlib import Path

import click

from ibkr_datafetcher.config import Config, load_config
from ibkr_datafetcher.db import Database
from ibkr_datafetcher.ibkr_client import IBKRClient
from ibkr_datafetcher.kline_fetcher import KlineFetcher
from ibkr_datafetcher.news_fetcher import NewsFetcher
from ibkr_datafetcher.rate_limiter import RateLimiter, RateLimitConfig
from ibkr_datafetcher.types import SymbolConfig, SyncProgress, Timeframe


def load_symbols(symbols_str: str | None, config: Config) -> list[SymbolConfig]:
    if symbols_str:
        symbol_names = [s.strip() for s in symbols_str.split(",")]
        return [s for s in config.sync.symbols if s.symbol in symbol_names]
    return config.sync.symbols


def parse_timeframes(timeframes_str: str | None) -> list[Timeframe]:
    if not timeframes_str:
        return []
    tf_names = [t.strip() for t in timeframes_str.split(",")]
    result = []
    for name in tf_names:
        try:
            result.append(Timeframe[name])
        except KeyError:
            pass
    return result


def format_progress(progress: SyncProgress, rate_stats: dict) -> str:
    bar_w = 20
    done = int(bar_w * progress.current_range / max(progress.total_ranges, 1))
    pbar = "=" * done + ">" + " " * (bar_w - done - 1)
    pct = progress.current_range / max(progress.total_ranges, 1) * 100

    hist_used = rate_stats.get("hist", {}).get("used", 0)
    news_used = rate_stats.get("news", {}).get("used", 0)

    lines = [
        f"  当前: [{progress.symbol} / {progress.timeframe}] "
        f"第 {progress.current_range}/{progress.total_ranges} 段",
        f"  进度: [{pbar}] {pct:.0f}% ({progress.bars_fetched} bars)",
        f"  限制: hist {hist_used}/6 req/min | news {news_used}/3 req/min",
    ]
    if progress.eta_sec is not None:
        lines.append(f"  ETA: {progress.eta_sec:.0f}s")
    return "\n".join(lines)


@click.group()
def main():
    """IBKR K 线数据同步工具"""


@main.command()
@click.option("--symbols", help="标的列表，逗号分隔")
@click.option("--timeframes", help="周期列表，逗号分隔")
@click.option("--config", default="configs/config.yaml", type=click.Path())
def sync(symbols, timeframes, config):
    """同步 K 线数据"""
    try:
        cfg = load_config(config)
    except Exception as e:
        click.echo(f"配置加载失败: {e}", err=True)
        sys.exit(1)

    symbol_list = load_symbols(symbols, cfg)
    if not symbol_list:
        click.echo("没有找到匹配的标的", err=True)
        sys.exit(1)

    timeframe_list = parse_timeframes(timeframes)
    if not timeframe_list:
        click.echo("没有找到匹配的周期", err=True)
        sys.exit(1)

    db = Database(cfg.database.path)
    db.start()

    try:
        client = IBKRClient(cfg.gateway)
        if not client.connect():
            click.echo("连接 IBKR Gateway 失败", err=True)
            sys.exit(1)

        try:
            rate_limiter = RateLimiter(RateLimitConfig())
            fetcher = KlineFetcher(client, rate_limiter, db)

            def progress_callback(p: SyncProgress):
                stats = rate_limiter.get_stats()
                click.echo(format_progress(p, stats))

            click.echo(f"开始同步 {len(symbol_list)} 个标的...")
            result = fetcher.sync_all(symbol_list, timeframe_list, progress_callback)

            click.echo("\n同步完成:")
            click.echo(f"  总 bars: {result['total_bars']}")
            click.echo(f"  处理标的: {result['symbols_processed']}")
            if result["errors"]:
                click.echo(f"  错误: {len(result['errors'])}")
                for err in result["errors"][:5]:
                    click.echo(f"    - {err}")

        finally:
            client.disconnect()
    finally:
        db.stop()


@main.command()
@click.argument("symbol")
@click.option("--timeframe", "timeframe_str", required=True)
@click.option("--from-time", "from_time")
@click.option("--to-time", "to_time")
@click.option("--limit", type=int, default=100)
@click.option(
    "--format", "fmt",
    type=click.Choice(["table", "csv", "json"]),
    default="table",
)
@click.option("--output", type=click.Path(), help="输出文件路径")
@click.option("--config", default="configs/config.yaml", type=click.Path())
def query(symbol, timeframe_str, from_time, to_time, limit, fmt, output, config):
    """查询本地 K 线数据"""
    try:
        cfg = load_config(config)
    except Exception as e:
        click.echo(f"配置加载失败: {e}", err=True)
        sys.exit(1)

    try:
        timeframe = Timeframe[timeframe_str]
    except KeyError:
        click.echo(f"无效的时间周期: {timeframe_str}", err=True)
        sys.exit(1)

    db = Database(cfg.database.path)
    db.start()

    try:
        from_ts = 0
        if from_time:
            from_ts = int(datetime.fromisoformat(from_time).timestamp())
        to_ts = int(time.time())
        if to_time:
            to_ts = int(datetime.fromisoformat(to_time).timestamp())

        bars = db.get_bars(symbol, timeframe.name, from_ts, to_ts)
        if limit:
            bars = bars[:limit]

        if not bars:
            click.echo("没有找到数据")
            return

        if fmt == "json":
            data = [
                {
                    "timestamp": b.timestamp,
                    "open": b.open,
                    "high": b.high,
                    "low": b.low,
                    "close": b.close,
                    "volume": b.volume,
                }
                for b in bars
            ]
            content = _json.dumps(data, indent=2)
        elif fmt == "csv":
            lines = ["timestamp,open,high,low,close,volume"]
            for b in bars:
                lines.append(
                    f"{b.timestamp},{b.open},{b.high},"
                    f"{b.low},{b.close},{b.volume}"
                )
            content = "\n".join(lines)
        else:
            header = f"{'Timestamp':<12} {'Open':>10} {'High':>10}"
            header2 = f"{'Low':>10} {'Close':>10} {'Volume':>12}"
            lines = [f"{header} {header2}"]
            for b in bars:
                dt = datetime.fromtimestamp(b.timestamp).strftime("%Y-%m-%d %H:%M")
                line = (
                    f"{dt:<12} {b.open:>10.2f} {b.high:>10.2f} "
                    f"{b.low:>10.2f} {b.close:>10.2f} {b.volume:>12.0f}"
                )
                lines.append(line)
            content = "\n".join(lines)

        if output:
            Path(output).write_text(content, encoding="utf-8")
            click.echo(f"已保存到 {output}")
        else:
            click.echo(content)

    finally:
        db.stop()


@main.command()
@click.option("--symbol", help="查询指定标的")
@click.option("--config", default="configs/config.yaml", type=click.Path())
def status(symbol, config):
    """查看同步状态"""
    try:
        cfg = load_config(config)
    except Exception as e:
        click.echo(f"配置加载失败: {e}", err=True)
        sys.exit(1)

    db = Database(cfg.database.path)
    db.start()

    try:
        header = " | ".join([f"{h:<15}" for h in
                             ["Symbol", "Timeframe", "Latest Bar", "Bars", "Synced At"]])
        sep = "-" * len(header)
        click.echo(sep)
        click.echo(header)
        click.echo(sep)

        if symbol:
            for tf in ["D1", "H1", "M5"]:
                status_obj = db.get_sync_status(symbol, tf)
                if status_obj:
                    dt = datetime.fromtimestamp(
                        status_obj.latest_bar_time
                    ).strftime("%Y-%m-%d %H:%M")
                    synced = datetime.fromisoformat(
                        status_obj.synced_at
                    ).strftime("%Y-%m-%d %H:%M")
                    row = " | ".join([
                        f"{symbol:<15}", f"{tf:<15}", f"{dt:<15}",
                        f"{str(status_obj.bar_count):<15}", f"{synced:<15}",
                    ])
                    click.echo(row)
        else:
            for sym_cfg in cfg.sync.symbols[:10]:
                for tf in ["D1", "H1", "M5"]:
                    status_obj = db.get_sync_status(sym_cfg.symbol, tf)
                    if status_obj:
                        dt = datetime.fromtimestamp(
                            status_obj.latest_bar_time
                        ).strftime("%Y-%m-%d %H:%M")
                        synced = datetime.fromisoformat(
                            status_obj.synced_at
                        ).strftime("%Y-%m-%d %H:%M")
                        row = " | ".join([
                            f"{sym_cfg.symbol:<15}", f"{tf:<15}", f"{dt:<15}",
                            f"{str(status_obj.bar_count):<15}", f"{synced:<15}",
                        ])
                        click.echo(row)

    finally:
        db.stop()


@main.command()
@click.option("--symbols", required=True, help="标的列表，逗号分隔")
@click.option("--days", default=30, help="拉取最近天数")
@click.option("--config", default="configs/config.yaml", type=click.Path())
def news(symbols, days, config):
    """拉取新闻数据"""
    try:
        cfg = load_config(config)
    except Exception as e:
        click.echo(f"配置加载失败: {e}", err=True)
        sys.exit(1)

    symbol_names = [s.strip() for s in symbols.split(",")]
    symbol_list = [s for s in cfg.sync.symbols if s.symbol in symbol_names]
    if not symbol_list:
        click.echo("没有找到匹配的标的", err=True)
        sys.exit(1)

    db = Database(cfg.database.path)
    db.start()

    try:
        client = IBKRClient(cfg.gateway)
        if not client.connect():
            click.echo("连接 IBKR Gateway 失败", err=True)
            sys.exit(1)

        try:
            rate_limiter = RateLimiter(RateLimitConfig())
            news_fetcher = NewsFetcher(client, rate_limiter, db)

            click.echo(f"开始拉取 {len(symbol_list)} 个标的的新闻...")
            total_news = 0
            for sym in symbol_list:
                result = news_fetcher.fetch_symbol_news(sym, days=days)
                total_news += result["news_count"]
                click.echo(f"  {sym.symbol}: {result['news_count']} 条新闻")
                if result["errors"]:
                    for err in result["errors"][:3]:
                        click.echo(f"    错误: {err}")

            click.echo(f"\n完成: 共 {total_news} 条新闻")

        finally:
            client.disconnect()
    finally:
        db.stop()


@main.command()
@click.option("--schedule", required=True, help="Cron 表达式，如 '0 9,16 * * 1-5'")
@click.option("--config", default="configs/config.yaml", type=click.Path())
def serve(schedule, config):
    """启动定时同步服务"""
    try:
        cfg = load_config(config)
    except Exception as e:
        click.echo(f"配置加载失败: {e}", err=True)
        sys.exit(1)

    from ibkr_datafetcher.scheduler import Scheduler

    db = Database(cfg.database.path)
    db.start()

    try:
        client = IBKRClient(cfg.gateway)
        if not client.connect():
            click.echo("连接 IBKR Gateway 失败", err=True)
            sys.exit(1)

        try:
            rate_limiter = RateLimiter(RateLimitConfig())
            fetcher = KlineFetcher(client, rate_limiter, db)
            scheduler = Scheduler(fetcher, cfg.sync.symbols, None)

            click.echo(f"启动定时同步服务 (cron: {schedule})")
            click.echo("按 Ctrl+C 停止")

            scheduler.start(schedule)

        finally:
            scheduler.stop()
            client.disconnect()
    finally:
        db.stop()


@main.command()
@click.option("--config", default="configs/config.yaml", type=click.Path())
def reconnect(config):
    """检测/重连 IBKR Gateway"""
    try:
        cfg = load_config(config)
    except Exception as e:
        click.echo(f"配置加载失败: {e}", err=True)
        sys.exit(1)

    client = IBKRClient(cfg.gateway)

    if client.is_connected():
        click.echo("已连接 IBKR Gateway")
        return

    click.echo("正在连接 IBKR Gateway...")
    if client.reconnect(max_retries=3):
        click.echo("连接成功")
    else:
        click.echo("连接失败", err=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
