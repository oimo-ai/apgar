from __future__ import annotations

import json
from datetime import datetime, timedelta

import pytest

from apgar.config import Settings
from apgar.storage.memory import InMemoryEventStore, InMemoryMetaStore
from apgar.worker import main as worker_main
from apgar.worker.heartbeat import HEARTBEAT_KEY, write
from apgar.worker.main import run_worker


@pytest.fixture(autouse=True)
def _no_jobs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(worker_main, "start_http_server", lambda port: None)
    monkeypatch.setattr(worker_main, "register_jobs", lambda *args: [])


async def test_worker_clears_heartbeat_on_shutdown(
    settings: Settings,
    mem_stores: tuple[InMemoryEventStore, InMemoryMetaStore],
    fixed_now: datetime,
) -> None:
    event_store, meta = mem_stores
    await run_worker(settings, event_store, meta, lambda: fixed_now)
    assert await meta.get_setting(HEARTBEAT_KEY) is None


async def test_refused_worker_keeps_other_heartbeat(
    settings: Settings,
    mem_stores: tuple[InMemoryEventStore, InMemoryMetaStore],
    fixed_now: datetime,
) -> None:
    event_store, meta = mem_stores
    await write(meta, "other", fixed_now - timedelta(seconds=5))
    with pytest.raises(SystemExit) as caught:
        await run_worker(settings, event_store, meta, lambda: fixed_now)
    assert caught.value.code == 1
    raw = await meta.get_setting(HEARTBEAT_KEY)
    assert raw is not None
    assert json.loads(raw)["instance_id"] == "other"
