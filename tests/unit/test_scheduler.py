from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

import pytest

from apgar.worker.scheduler import PeriodicJob


async def test_job_exception_is_logged_and_loop_continues(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = {"n": 0}
    stop = asyncio.Event()

    async def run(_now: datetime) -> None:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("boom")
        stop.set()

    async def fake_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr("apgar.worker.scheduler.asyncio.sleep", fake_sleep)
    job = PeriodicJob("unit-boom", 0.01, run)
    with caplog.at_level(logging.ERROR, logger="apgar.worker.scheduler"):
        await job.loop(lambda: datetime(2026, 10, 8, tzinfo=UTC), stop)
    assert calls["n"] == 2
    assert any(getattr(record, "job", None) == "unit-boom" for record in caplog.records)
    assert any(
        record.exc_info is not None and "boom" in str(record.exc_info[1])
        for record in caplog.records
    )


async def test_job_runs_at_interval(monkeypatch: pytest.MonkeyPatch) -> None:
    times = [
        datetime(2026, 10, 8, 9, 30, tzinfo=UTC),
        datetime(2026, 10, 8, 9, 30, 5, tzinfo=UTC),
    ]
    seen: list[datetime] = []
    slept: list[float] = []
    stop = asyncio.Event()
    upcoming = iter(times)

    def clock() -> datetime:
        return next(upcoming)

    async def run(now: datetime) -> None:
        seen.append(now)
        if len(seen) == 2:
            stop.set()

    async def fake_sleep(seconds: float) -> None:
        slept.append(seconds)

    monkeypatch.setattr("apgar.worker.scheduler.asyncio.sleep", fake_sleep)
    job = PeriodicJob("unit-interval", 5, run)
    await job.loop(clock, stop)
    assert seen == times
    assert slept == [5]
