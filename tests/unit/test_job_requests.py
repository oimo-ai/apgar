from __future__ import annotations

import asyncio
from datetime import datetime

from prometheus_client import REGISTRY

from apgar.domain.enums import JobRequestKind
from apgar.domain.models import JobRequest
from apgar.storage.memory import InMemoryMetaStore
from apgar.worker.jobs.requests import JobRequestProcessor


def _job(now: datetime, kind: JobRequestKind, job_id: str) -> JobRequest:
    return JobRequest(
        id=job_id,
        agent_id="agent",
        release="rel",
        kind=kind,
        payload={},
        requested_at=now,
        processed_at=None,
        updated_at=now,
    )


async def test_handler_dispatch_and_poison(fixed_now: datetime) -> None:
    meta = InMemoryMetaStore()
    processor = JobRequestProcessor(meta, asyncio.Lock())
    handled: list[str] = []

    async def record(job: JobRequest, _now: datetime) -> None:
        handled.append(job.id)

    async def boom(_job: JobRequest, _now: datetime) -> None:
        raise RuntimeError("poison")

    processor.handlers[JobRequestKind.apply_events] = record
    processor.handlers[JobRequestKind.evaluate] = boom
    await meta.enqueue_job(_job(fixed_now, JobRequestKind.apply_events, "a1"))
    await meta.enqueue_job(_job(fixed_now, JobRequestKind.evaluate, "e1"))
    before = REGISTRY.get_sample_value("apgar_job_requests_failed_total", {"kind": "evaluate"}) or 0
    await processor.run(fixed_now)
    assert handled == ["a1"]
    assert await meta.pending_jobs(10) == []
    after = REGISTRY.get_sample_value("apgar_job_requests_failed_total", {"kind": "evaluate"}) or 0
    assert after == before + 1


async def test_unhandled_kind_left_pending(fixed_now: datetime) -> None:
    meta = InMemoryMetaStore()
    processor = JobRequestProcessor(meta, asyncio.Lock())
    await meta.enqueue_job(_job(fixed_now, JobRequestKind.demo_seed, "d1"))
    await processor.run(fixed_now)
    pending = await meta.pending_jobs(10)
    assert len(pending) == 1
    assert pending[0].kind is JobRequestKind.demo_seed
