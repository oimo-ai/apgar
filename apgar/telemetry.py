from __future__ import annotations

import logging
import math
import uuid
from datetime import UTC, datetime

from apgar import __version__
from apgar.config import Settings
from apgar.domain.enums import VerdictState
from apgar.domain.time import to_iso
from apgar.storage.interfaces import EventStore, MetaStore
from apgar.storage.types import ReleaseFilters

_LOG = logging.getLogger("apgar.telemetry")

_VERDICT_ORDER = (
    VerdictState.PASS,
    VerdictState.FAIL,
    VerdictState.INCONCLUSIVE,
    VerdictState.PENDING,
)


def turns_per_day_magnitude(turns: int) -> int:
    if turns < 10:
        return 0
    return math.floor(math.log10(turns))


def env_disables_telemetry(settings: Settings) -> bool:
    return str(settings.telemetry) == "0"


def log_startup(settings: Settings) -> None:
    if env_disables_telemetry(settings):
        _LOG.info("telemetry disabled")


def _day(now: datetime) -> str:
    aware = now if now.tzinfo is not None else now.replace(tzinfo=UTC)
    return aware.astimezone(UTC).date().isoformat()


async def telemetry_is_enabled(settings: Settings, meta_store: MetaStore) -> bool:
    if env_disables_telemetry(settings):
        return False
    stored = await meta_store.get_setting("telemetry.enabled")
    return stored != "0"


async def _instance_id(meta_store: MetaStore, now: datetime) -> str:
    stored = await meta_store.get_setting("telemetry.instance_id")
    if stored:
        return stored
    created = str(uuid.uuid4())
    await meta_store.set_setting("telemetry.instance_id", created, now)
    return created


async def _verdict_counts(meta_store: MetaStore, agent_id: str) -> dict[str, int]:
    counts = {state.value: 0 for state in _VERDICT_ORDER}
    offset = 0
    while True:
        rows = await meta_store.list_releases(
            ReleaseFilters(agent_id=agent_id, limit=500, offset=offset)
        )
        for row in rows:
            key = row.state.value
            if key in counts:
                counts[key] += 1
        if len(rows) < 500:
            return counts
        offset += 500


async def build_payload(
    meta_store: MetaStore,
    event_store: EventStore,
    settings: Settings,
    now: datetime,
) -> dict[str, object]:
    del settings
    instance_id = await _instance_id(meta_store, now)
    agents = await meta_store.list_agents()
    demo = [agent for agent in agents if agent.is_demo]
    live = [agent for agent in agents if not agent.is_demo]
    turns = 0
    counts = {state.value: 0 for state in _VERDICT_ORDER}
    for agent in live:
        activity = await event_store.agent_activity(agent.id, now)
        turns += activity.turns_24h
        agent_counts = await _verdict_counts(meta_store, agent.id)
        for key, value in agent_counts.items():
            counts[key] += value
    return {
        "schema": 1,
        "instance_id": instance_id,
        "version": __version__,
        "agents_non_demo": len(live),
        "agents_demo": len(demo),
        "turns_per_day_magnitude": turns_per_day_magnitude(turns),
        "verdict_counts": counts,
        "sent_at": to_iso(now),
    }


def report_day(now: datetime) -> str:
    return _day(now)
