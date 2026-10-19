from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime

from apgar.actions.dispatcher import TransitionEmitter
from apgar.assembly.assembler import Assembler
from apgar.config import Settings
from apgar.domain.enums import JobRequestKind
from apgar.domain.models import Agent, TurnRow
from apgar.domain.time import utcnow
from apgar.normalize.normalizer import HmacKeys
from apgar.storage.interfaces import EventStore, MetaStore
from apgar.verdict.evaluate import Evaluator
from apgar.verdict.pool import EvaluatorPool
from apgar.worker.heartbeat import HEARTBEAT_INTERVAL, write
from apgar.worker.jobs.assembly import AssemblyJob
from apgar.worker.jobs.finalize import FinalizeJob
from apgar.worker.jobs.handlers import (
    ApplyEventsHandler,
    DemoSeedHandler,
    EvaluateHandler,
)
from apgar.worker.jobs.langfuse_sync import LangfuseSyncJob
from apgar.worker.jobs.notifications import NotificationDispatcher
from apgar.worker.jobs.release_discovery import ReleaseDiscovery
from apgar.worker.jobs.requests import JobRequestProcessor
from apgar.worker.jobs.retention import RetentionJob
from apgar.worker.jobs.rollup import RollupJob
from apgar.worker.jobs.telemetry import TelemetryJob
from apgar.worker.jobs.verdict import VerdictJob
from apgar.worker.scheduler import PeriodicJob


def _close_pool(pool: EvaluatorPool) -> Callable[[], Awaitable[None]]:
    async def _close() -> None:
        pool.close()

    return _close


def register_jobs(
    settings: Settings,
    stores: tuple[EventStore, MetaStore],
    release_lock: asyncio.Lock | None = None,
) -> list[PeriodicJob]:
    event_store, meta_store = stores
    lock = asyncio.Lock() if release_lock is None else release_lock
    keys = HmacKeys.from_settings(settings)
    emitter = TransitionEmitter(meta_store, settings, utcnow)
    discovery = ReleaseDiscovery(meta_store, lock, on_registered=emitter.on_registered)

    async def on_turn(turn: TurnRow, agent: Agent, assembled_at: datetime) -> None:
        await discovery.on_turn_assembled(turn, agent, assembled_at)

    assembler = Assembler(
        event_store,
        meta_store,
        settings,
        keys,
        utcnow,
        on_turn_assembled=on_turn,
    )
    langfuse = LangfuseSyncJob(event_store, meta_store, settings, keys)
    processor = JobRequestProcessor(meta_store, lock)
    pool = EvaluatorPool(settings.evaluator_processes)
    evaluator = Evaluator(
        event_store,
        meta_store,
        settings,
        pool,
        utcnow,
        [emitter.on_transition],
        lock,
    )
    processor.handlers[JobRequestKind.evaluate] = EvaluateHandler(evaluator, meta_store).handle
    processor.handlers[JobRequestKind.apply_events] = ApplyEventsHandler(
        evaluator, meta_store
    ).handle
    processor.handlers[JobRequestKind.demo_seed] = DemoSeedHandler(
        event_store, meta_store, settings, evaluator
    ).handle
    retention = RetentionJob(
        event_store,
        meta_store,
        getattr(event_store, "client", None),
        settings.late_span_days,
    )
    notifier = NotificationDispatcher(meta_store, clock=utcnow)
    telemetry = TelemetryJob(event_store, meta_store, settings)
    verdict = VerdictJob(meta_store, evaluator, settings)
    finalize = FinalizeJob(meta_store, evaluator)

    async def heartbeat(now: datetime) -> None:
        await write(meta_store, settings.worker_instance_id, now)

    return [
        PeriodicJob(
            name="heartbeat",
            interval_seconds=float(HEARTBEAT_INTERVAL),
            run=heartbeat,
        ),
        PeriodicJob(
            name="assembly",
            interval_seconds=float(settings.assembly_interval_seconds),
            run=AssemblyJob(assembler).run,
        ),
        PeriodicJob(
            name="rollup",
            interval_seconds=float(settings.rollup_interval_seconds),
            run=RollupJob(event_store, meta_store, lock).run,
        ),
        PeriodicJob(
            name="langfuse_sync",
            interval_seconds=float(settings.langfuse_sync_interval_seconds),
            run=langfuse.run,
            aclose=langfuse.aclose,
        ),
        PeriodicJob(
            name="requests",
            interval_seconds=float(settings.requests_interval_seconds),
            run=processor.run,
        ),
        PeriodicJob(
            name="retention",
            interval_seconds=86400,
            run=retention.run,
        ),
        PeriodicJob(
            name="verdict",
            interval_seconds=60,
            run=verdict.run,
            aclose=_close_pool(pool),
        ),
        PeriodicJob(
            name="finalize",
            interval_seconds=300,
            run=finalize.run,
        ),
        PeriodicJob(
            name="notifications",
            interval_seconds=5,
            run=notifier.run,
            aclose=notifier.aclose,
        ),
        PeriodicJob(
            name="telemetry",
            interval_seconds=3600,
            run=telemetry.run,
            aclose=telemetry.aclose,
        ),
    ]
