from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime

from prometheus_client import Counter, Gauge, Histogram

_LOG = logging.getLogger("apgar.worker.scheduler")

JOB_ERRORS = Counter(
    "apgar_job_errors_total",
    "Background job failures.",
    ["job"],
)
JOB_LAST_SUCCESS = Gauge(
    "apgar_job_last_success_timestamp_seconds",
    "Unix time of the last successful job run.",
    ["job"],
)
JOB_DURATION = Histogram(
    "apgar_job_duration_seconds",
    "Background job duration in seconds.",
    ["job"],
)


@dataclass(slots=True)
class PeriodicJob:
    name: str
    interval_seconds: float
    run: Callable[[datetime], Awaitable[None]]
    aclose: Callable[[], Awaitable[None]] | None = None

    async def loop(self, clock: Callable[[], datetime], stop_event: asyncio.Event) -> None:
        while not stop_event.is_set():
            now = clock()
            started = time.perf_counter()
            try:
                await self.run(now)
            except Exception:
                _LOG.exception("job failed", extra={"job": self.name})
                JOB_ERRORS.labels(job=self.name).inc()
            else:
                JOB_LAST_SUCCESS.labels(job=self.name).set(now.timestamp())
            JOB_DURATION.labels(job=self.name).observe(time.perf_counter() - started)
            if stop_event.is_set():
                return
            await self._wait(stop_event)

    async def _wait(self, stop_event: asyncio.Event) -> None:
        sleep_task = asyncio.create_task(asyncio.sleep(self.interval_seconds))
        stop_task = asyncio.create_task(stop_event.wait())
        _done, pending = await asyncio.wait(
            {sleep_task, stop_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()
        for task in pending:
            with contextlib.suppress(asyncio.CancelledError):
                await task
