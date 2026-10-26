from __future__ import annotations

import asyncio
import logging
import signal
from collections.abc import Callable
from datetime import datetime

from prometheus_client import start_http_server

from apgar.config import Settings
from apgar.domain.time import utcnow
from apgar.net import any_address
from apgar.security import SecretBox
from apgar.storage.clickhouse.migrate import (
    EXPECTED_SCHEMA_VERSION,
    SchemaVersionError,
    is_unknown_database,
)
from apgar.storage.interfaces import EventStore, MetaStore
from apgar.telemetry import log_startup
from apgar.worker.heartbeat import AnotherWorkerRunning, clear, guard, write
from apgar.worker.jobs import register_jobs
from apgar.worker.reencrypt import reencrypt_connections

_LOG = logging.getLogger("apgar.worker")


async def run_worker(
    settings: Settings,
    event_store: EventStore,
    meta_store: MetaStore,
    clock: Callable[[], datetime] = utcnow,
) -> None:
    try:
        found = await meta_store.schema_version()
    except Exception as exc:
        if is_unknown_database(exc):
            raise SchemaVersionError(0, EXPECTED_SCHEMA_VERSION) from exc
        raise
    if found != EXPECTED_SCHEMA_VERSION:
        raise SchemaVersionError(found, EXPECTED_SCHEMA_VERSION)
    now = clock()
    try:
        await guard(meta_store, settings.worker_instance_id, now)
    except AnotherWorkerRunning:
        _LOG.error("another worker heartbeat is younger than 30 seconds; refusing to start")
        raise SystemExit(1) from None
    box = SecretBox(settings.secret_key, settings.secret_key_previous)
    if settings.secret_key_previous:
        await reencrypt_connections(meta_store, box, now)
    log_startup(settings)
    start_http_server(settings.worker_metrics_port, addr=any_address())
    await write(meta_store, settings.worker_instance_id, now)
    jobs = register_jobs(settings, (event_store, meta_store), asyncio.Lock())
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop_event.set)
    try:
        await asyncio.gather(*(job.loop(clock, stop_event) for job in jobs))
    finally:
        for job in jobs:
            if job.aclose is not None:
                await job.aclose()
    try:
        await clear(meta_store, clock())
    except Exception:
        _LOG.exception("failed to clear worker heartbeat on shutdown")
