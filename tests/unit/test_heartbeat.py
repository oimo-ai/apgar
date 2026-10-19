from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from apgar.storage.memory import InMemoryEventStore, InMemoryMetaStore
from apgar.worker.heartbeat import AnotherWorkerRunning, clear, guard, write


async def test_guard_passes_without_heartbeat(
    mem_stores: tuple[InMemoryEventStore, InMemoryMetaStore],
    fixed_now: datetime,
) -> None:
    _event_store, meta = mem_stores
    await guard(meta, "me", fixed_now)


async def test_guard_passes_with_stale_heartbeat(
    mem_stores: tuple[InMemoryEventStore, InMemoryMetaStore],
    fixed_now: datetime,
) -> None:
    _event_store, meta = mem_stores
    await write(meta, "other", fixed_now - timedelta(seconds=31))
    await guard(meta, "me", fixed_now)


async def test_guard_rejects_fresh_foreign_heartbeat(
    mem_stores: tuple[InMemoryEventStore, InMemoryMetaStore],
    fixed_now: datetime,
) -> None:
    _event_store, meta = mem_stores
    await write(meta, "other", fixed_now - timedelta(seconds=5))
    with pytest.raises(AnotherWorkerRunning) as caught:
        await guard(meta, "me", fixed_now)
    assert caught.value.other_instance_id == "other"


async def test_guard_accepts_own_heartbeat(
    mem_stores: tuple[InMemoryEventStore, InMemoryMetaStore],
    fixed_now: datetime,
) -> None:
    _event_store, meta = mem_stores
    await write(meta, "me", fixed_now - timedelta(seconds=1))
    await guard(meta, "me", fixed_now)


async def test_clear_removes_heartbeat_so_another_worker_can_start(
    mem_stores: tuple[InMemoryEventStore, InMemoryMetaStore],
    fixed_now: datetime,
) -> None:
    _event_store, meta = mem_stores
    await write(meta, "old", fixed_now)
    await clear(meta, fixed_now)
    await guard(meta, "new", fixed_now)
