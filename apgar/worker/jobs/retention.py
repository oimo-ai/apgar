from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from prometheus_client import Counter

from apgar.domain.retention import RETENTION_DEFAULTS, RETENTION_TTLS, TRACE_STATE_TTL
from apgar.storage.interfaces import EventStore, MetaStore

_LOG = logging.getLogger("apgar.retention")
_APPLIED = "retention.applied"
RUNS = Counter("apgar_retention_runs_total", "Retention job runs.")


def ttl_statements(values: dict[str, int], late_span_days: int) -> list[str]:
    statements = [
        f"ALTER TABLE {table} MODIFY TTL {expression} + INTERVAL {values[key]} DAY"
        for table, expression, key in RETENTION_TTLS
    ]
    table, expression = TRACE_STATE_TTL
    statements.append(
        f"ALTER TABLE {table} MODIFY TTL {expression} + INTERVAL {late_span_days} DAY"
    )
    return statements


class RetentionJob:
    def __init__(
        self,
        event_store: EventStore,
        meta_store: MetaStore,
        client: Any | None,
        late_span_days: int,
    ) -> None:
        self._events = event_store
        self._meta = meta_store
        self._client = client
        self._late_span_days = late_span_days

    async def _values(self) -> dict[str, int]:
        values: dict[str, int] = {}
        for key, default in RETENTION_DEFAULTS.items():
            raw = await self._meta.get_setting(f"retention.{key}")
            values[key] = default if raw is None else int(raw)
        return values

    def _fingerprint(self, values: dict[str, int]) -> str:
        # trace_state_days is recorded here only. Changing APGAR_LATE_SPAN_DAYS
        # must reapply that table's TTL, and the key is not a settings field.
        recorded = {**values, "trace_state_days": self._late_span_days}
        return json.dumps(recorded, sort_keys=True, separators=(",", ":"))

    async def run(self, now: datetime) -> None:
        values = await self._values()
        encoded = self._fingerprint(values)
        applied = await self._meta.get_setting(_APPLIED)
        if applied != encoded:
            if self._client is not None:
                for statement in ttl_statements(values, self._late_span_days):
                    await self._client.command(statement)
            await self._meta.set_setting(_APPLIED, encoded, now)
        agents = await self._meta.list_agents(include_demo=True, include_deleted=True)
        for agent in agents:
            if agent.deleted_at is None:
                continue
            await self._events.purge_agent(agent.id, sync=True)
            await self._meta.finalize_agent_deletion(agent.id, now)
        RUNS.inc()
        _LOG.info("retention complete", extra={"agents": sum(1 for a in agents if a.deleted_at)})
