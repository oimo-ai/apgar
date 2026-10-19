from __future__ import annotations

import json
from datetime import datetime

from apgar.domain.time import from_iso, to_iso
from apgar.storage.interfaces import MetaStore

HEARTBEAT_KEY = "worker.heartbeat"
HEARTBEAT_INTERVAL = 10
HEARTBEAT_STALE_AFTER = 30


class AnotherWorkerRunning(Exception):
    def __init__(self, other_instance_id: str, age_seconds: float) -> None:
        self.other_instance_id = other_instance_id
        self.age_seconds = age_seconds
        super().__init__(other_instance_id)


async def guard(meta_store: MetaStore, instance_id: str, now: datetime) -> None:
    raw = await meta_store.get_setting(HEARTBEAT_KEY)
    if not raw:
        return
    try:
        payload = json.loads(raw)
        other = str(payload["instance_id"])
        seen = from_iso(str(payload["ts"]))
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return
    age = (now - seen).total_seconds()
    if age < HEARTBEAT_STALE_AFTER and other != instance_id:
        raise AnotherWorkerRunning(other, age)


async def clear(meta_store: MetaStore, now: datetime) -> None:
    await meta_store.delete_setting(HEARTBEAT_KEY, now)


async def write(meta_store: MetaStore, instance_id: str, now: datetime) -> None:
    payload = json.dumps(
        {"instance_id": instance_id, "ts": to_iso(now)},
        separators=(",", ":"),
        sort_keys=True,
    )
    await meta_store.set_setting(HEARTBEAT_KEY, payload, now)
