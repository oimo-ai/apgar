from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime

from prometheus_client import Counter

from apgar.domain.enums import JobRequestKind
from apgar.domain.models import JobRequest
from apgar.storage.interfaces import MetaStore

_LOG = logging.getLogger("apgar.jobs")
FAILURES = Counter(
    "apgar_job_requests_failed_total",
    "Job requests whose handler raised.",
    ["kind"],
)


class JobRequestProcessor:
    def __init__(self, meta_store: MetaStore, release_lock: asyncio.Lock) -> None:
        self._meta = meta_store
        self._lock = release_lock
        self.handlers: dict[JobRequestKind, Callable[[JobRequest, datetime], Awaitable[None]]] = {}
        self._warned: set[JobRequestKind] = set()

    async def run(self, now: datetime) -> None:
        jobs = await self._meta.pending_jobs(limit=100)
        for job in jobs:
            handler = self.handlers.get(job.kind)
            if handler is None:
                if job.kind not in self._warned:
                    _LOG.warning("no handler for job kind", extra={"kind": job.kind.value})
                    self._warned.add(job.kind)
                continue
            try:
                await handler(job, now)
            except Exception:
                _LOG.exception("job request failed", extra={"kind": job.kind.value})
                FAILURES.labels(kind=job.kind.value).inc()
            await self._meta.complete_job(job, now)
