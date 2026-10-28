from __future__ import annotations

import asyncio
import json
from typing import Any, NoReturn

import click
import uvicorn

from apgar import __version__
from apgar.api.app import create_app
from apgar.assembly.assembler import Assembler
from apgar.config import Settings, load_settings
from apgar.demo.generator import DEMO_CLOCK, purge, seed, simulate_verdicts
from apgar.domain.time import utcnow
from apgar.logging import setup_logging
from apgar.net import listen_socket
from apgar.normalize.normalizer import HmacKeys
from apgar.security import SecretBox
from apgar.storage.clickhouse.client import create_client
from apgar.storage.clickhouse.event_store import ClickHouseEventStore
from apgar.storage.clickhouse.meta_store import ClickHouseMetaStore
from apgar.storage.clickhouse.migrate import (
    EXPECTED_SCHEMA_VERSION,
    SchemaVersionError,
    check_schema_version,
    is_unknown_database,
    migrate,
    wait_for_schema,
)
from apgar.verdict.evaluate import Evaluator
from apgar.verdict.pool import InlinePool
from apgar.worker.main import run_worker


def _fail(exc: BaseException) -> NoReturn:
    if isinstance(exc, SchemaVersionError):
        click.echo(str(exc), err=True)
        raise SystemExit(3) from exc
    if is_unknown_database(exc):
        click.echo(str(SchemaVersionError(0, EXPECTED_SCHEMA_VERSION)), err=True)
        raise SystemExit(3) from exc
    click.echo(str(exc), err=True)
    raise SystemExit(1) from exc


def _box(settings: Settings) -> SecretBox:
    return SecretBox(settings.secret_key, settings.secret_key_previous)


def _meta(client: Any, settings: Settings) -> ClickHouseMetaStore:
    return ClickHouseMetaStore(client, _box(settings))


async def _open_client(settings: Settings) -> Any:
    try:
        return await create_client(settings)
    except Exception as exc:
        _fail(exc)


async def _run_migrate(timeout_seconds: int) -> int:
    settings = load_settings()
    setup_logging(settings.log_level)
    try:
        return await migrate(settings, timeout_seconds)
    except Exception as exc:
        _fail(exc)


async def _run_wait_for_schema(timeout_seconds: int) -> int:
    settings = load_settings()
    setup_logging(settings.log_level)
    try:
        return await wait_for_schema(settings, timeout_seconds)
    except Exception as exc:
        _fail(exc)


async def _run_api() -> None:
    settings = load_settings()
    setup_logging(settings.log_level)
    client = await _open_client(settings)
    try:
        await check_schema_version(client)
    except Exception as exc:
        await client.close()
        _fail(exc)
    app = create_app(settings, ClickHouseEventStore(client), _meta(client, settings))
    app.state.client = client
    config = uvicorn.Config(
        app,
        host=settings.api_host or "::",
        port=settings.api_port,
        log_config=None,
    )
    # Without a host, the API listens on every IPv4 and IPv6 address.
    sockets = None if settings.api_host else [listen_socket(settings.api_port)]
    await uvicorn.Server(config).serve(sockets=sockets)


async def _run_worker() -> None:
    settings = load_settings()
    setup_logging(settings.log_level)
    client = await _open_client(settings)
    try:
        await check_schema_version(client)
        await run_worker(settings, ClickHouseEventStore(client), _meta(client, settings))
    except SystemExit:
        raise
    except Exception as exc:
        _fail(exc)
    finally:
        await client.close()


@click.group()
@click.version_option(__version__, prog_name="apgar", message="%(prog)s %(version)s")
def main() -> None:
    """Release health for AI agents."""


@main.command("migrate")
@click.option(
    "--timeout",
    "timeout_seconds",
    default=0,
    show_default=True,
    type=click.IntRange(min=0),
    help="Seconds to keep retrying while ClickHouse is unreachable.",
)
def migrate_command(timeout_seconds: int) -> None:
    version = asyncio.run(_run_migrate(timeout_seconds))
    click.echo(f"schema version {version}")


@main.command("wait-for-schema")
@click.option(
    "--timeout",
    "timeout_seconds",
    default=300,
    show_default=True,
    type=click.IntRange(min=0),
    help="Seconds to wait for the schema version this image expects.",
)
def wait_for_schema_command(timeout_seconds: int) -> None:
    """Wait until `apgar migrate` has brought the schema to this version."""
    version = asyncio.run(_run_wait_for_schema(timeout_seconds))
    click.echo(f"schema version {version}")


@main.command("api")
def api_command() -> None:
    asyncio.run(_run_api())


@main.command("worker")
def worker_command() -> None:
    asyncio.run(_run_worker())


async def _demo_client(settings: Settings) -> tuple[Any, ClickHouseEventStore, ClickHouseMetaStore]:
    client = await _open_client(settings)
    try:
        await check_schema_version(client)
    except Exception:
        await client.close()
        raise
    return client, ClickHouseEventStore(client), _meta(client, settings)


async def _demo_seed(days: int, turns_per_day: int, seed_value: int, purge_first: bool) -> None:
    settings = load_settings()
    setup_logging(settings.log_level)
    client, event_store, meta_store = await _demo_client(settings)
    try:
        now = DEMO_CLOCK
        if purge_first:
            await purge(event_store, meta_store, now)
        elif await meta_store.get_setting("demo.seeded_at"):
            click.echo("demo data already present; use --purge-first", err=True)
        assembler = Assembler(
            event_store,
            meta_store,
            settings,
            HmacKeys.from_settings(settings),
            lambda: now,
        )
        summary = await seed(
            event_store,
            meta_store,
            settings,
            days,
            turns_per_day,
            seed_value,
            now,
            assembler,
        )
        evaluator = Evaluator(
            event_store,
            meta_store,
            settings,
            InlinePool(),
            utcnow,
            [],
            asyncio.Lock(),
        )
        summary["states"] = await simulate_verdicts(
            event_store, meta_store, settings, now, evaluator
        )
        click.echo(json.dumps(summary, indent=2, sort_keys=True))
    except Exception as exc:
        _fail(exc)
    finally:
        await client.close()


async def _demo_purge() -> None:
    settings = load_settings()
    setup_logging(settings.log_level)
    client, event_store, meta_store = await _demo_client(settings)
    try:
        purged = await purge(event_store, meta_store, utcnow())
        click.echo(json.dumps({"purged_agents": purged}))
    except Exception as exc:
        _fail(exc)
    finally:
        await client.close()


@main.group()
def demo() -> None:
    """Seed or purge demo traffic."""


@demo.command("seed")
@click.option("--days", default=14, show_default=True, type=int)
@click.option("--turns-per-day", default=300, show_default=True, type=int)
@click.option("--seed", "seed_value", default=42, show_default=True, type=int)
@click.option("--purge-first", is_flag=True)
def demo_seed_command(days: int, turns_per_day: int, seed_value: int, purge_first: bool) -> None:
    asyncio.run(_demo_seed(days, turns_per_day, seed_value, purge_first))


@demo.command("purge")
def demo_purge_command() -> None:
    asyncio.run(_demo_purge())
