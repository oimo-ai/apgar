from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import replace
from datetime import datetime
from uuid import uuid4

from prometheus_client import Counter

from apgar.domain.enums import JobRequestKind, ReasonCode, VerdictState
from apgar.domain.models import Agent, JobRequest, Release, TurnRow
from apgar.domain.time import monotonic_updated_at
from apgar.storage.interfaces import MetaStore
from apgar.storage.types import ReleaseFilters

_LOG = logging.getLogger("apgar.jobs")
RELEASES = Counter(
    "apgar_releases_registered_total",
    "Releases registered from assembled turns.",
    ["agent"],
)


def new_release(
    agent_id: str,
    release: str,
    first_seen: datetime,
    reason: ReasonCode,
    now: datetime,
) -> Release:
    return Release(
        agent_id=agent_id,
        release=release,
        first_seen=first_seen,
        state=VerdictState.PENDING,
        reason=reason,
        final=False,
        final_at=None,
        selected_baseline_release="",
        selected_baseline_mode="",
        baseline_unverified=False,
        verdict_summary={},
        verdict_updated_at=None,
        last_seen=None,
        turn_count=0,
        updated_at=now,
    )


class ReleaseDiscovery:
    def __init__(
        self,
        meta_store: MetaStore,
        release_lock: asyncio.Lock,
        on_registered: Callable[[Agent, Release], Awaitable[None]] | None = None,
    ) -> None:
        self._meta = meta_store
        self._lock = release_lock
        self._on_registered = on_registered

    async def _reason(self, agent_id: str, start_ts: datetime) -> ReasonCode:
        rows = await self._meta.list_releases(
            ReleaseFilters(agent_id=agent_id, limit=100_000, offset=0)
        )
        has_prior = any(row.first_seen < start_ts for row in rows)
        if has_prior:
            return ReasonCode.insufficient_sample
        return ReasonCode.no_baseline

    async def _registered(self, agent: Agent, release: Release) -> None:
        if self._on_registered is None:
            return
        try:
            await self._on_registered(agent, release)
        except Exception:
            _LOG.exception(
                "release registered hook failed",
                extra={"agent": agent.name, "release": release.release},
            )

    async def _enqueue(self, agent_id: str, release: str, now: datetime) -> None:
        await self._meta.enqueue_job(
            JobRequest(
                id=str(uuid4()),
                agent_id=agent_id,
                release=release,
                kind=JobRequestKind.evaluate,
                payload={},
                requested_at=now,
                processed_at=None,
                updated_at=now,
            )
        )

    async def on_turn_assembled(self, turn: TurnRow, agent: Agent, now: datetime) -> None:
        if turn.release == "untagged" or turn.late:
            return
        if agent.environment != "" and turn.environment != agent.environment:
            return
        async with self._lock:
            current = await self._meta.get_release(agent.id, turn.release)
            if current is None:
                reason = await self._reason(agent.id, turn.start_ts)
                created = new_release(
                    agent.id,
                    turn.release,
                    turn.start_ts,
                    reason,
                    monotonic_updated_at(now, None),
                )
                await self._meta.upsert_release(created)
                await self._enqueue(agent.id, turn.release, now)
                RELEASES.labels(agent=agent.name).inc()
                await self._registered(agent, created)
                return
            if current.first_seen > turn.start_ts:
                await self._meta.upsert_release(
                    replace(
                        current,
                        first_seen=turn.start_ts,
                        updated_at=monotonic_updated_at(now, current.updated_at),
                    )
                )
