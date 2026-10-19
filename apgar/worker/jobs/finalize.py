from __future__ import annotations

import logging
from datetime import datetime

from apgar.storage.interfaces import MetaStore
from apgar.storage.types import ReleaseFilters
from apgar.verdict.evaluate import Evaluator, end_of_monitoring, monitoring_cap
from apgar.verdict.state_machine import fold_events

_LOG = logging.getLogger("apgar.jobs")


class FinalizeJob:
    def __init__(self, meta_store: MetaStore, evaluator: Evaluator) -> None:
        self._meta = meta_store
        self._evaluator = evaluator

    async def run(self, now: datetime) -> None:
        agents = await self._meta.list_agents()
        for agent in agents:
            if agent.deleted_at is not None or agent.is_demo:
                continue
            releases = await self._meta.list_releases(
                ReleaseFilters(agent_id=agent.id, limit=100_000)
            )
            pending = [row for row in releases if not row.final]
            if not pending:
                continue
            for release in pending:
                user_state = fold_events(await self._meta.release_events(agent.id, release.release))
                cap = monitoring_cap(release, agent.verdict_settings, user_state)
                if end_of_monitoring(release, releases, now, cap, user_state.stopped_at) is None:
                    continue
                try:
                    await self._evaluator.evaluate_release(agent, release, now, False)
                except Exception:
                    _LOG.exception(
                        "finalization failed",
                        extra={"agent": agent.name, "release": release.release},
                    )
