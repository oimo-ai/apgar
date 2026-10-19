from __future__ import annotations

import asyncio
import logging
from dataclasses import replace
from datetime import datetime, timedelta

from apgar.api.metrics import ROLLUP_LAG
from apgar.domain.time import from_iso, monotonic_updated_at, to_iso, utcnow
from apgar.storage.interfaces import EventStore, MetaStore

_LOG = logging.getLogger("apgar.rollup")
_WATERMARK = "rollup.watermark"


class RollupJob:
    def __init__(
        self,
        event_store: EventStore,
        meta_store: MetaStore,
        release_lock: asyncio.Lock,
    ) -> None:
        self._events = event_store
        self._meta = meta_store
        self._release_lock = release_lock

    async def run(self, now: datetime) -> None:
        raw = await self._meta.get_setting(_WATERMARK)
        since = from_iso(raw) if raw else now - timedelta(days=30)
        agents = await self._events.dirty_agents(since, now)
        for agent_id in agents:
            for item in await self._events.release_activity(agent_id):
                async with self._release_lock:
                    current = await self._meta.get_release(agent_id, item.release)
                    if current is None:
                        continue
                    await self._meta.upsert_release(
                        replace(
                            current,
                            last_seen=item.last_seen,
                            turn_count=item.turn_count,
                            updated_at=monotonic_updated_at(now, current.updated_at),
                        )
                    )
        await self._meta.set_setting(_WATERMARK, to_iso(now), monotonic_updated_at(now, utcnow()))
        ROLLUP_LAG.set(max(0.0, (now - since).total_seconds()))
        _LOG.info("rollup complete", extra={"agents": len(agents)})
