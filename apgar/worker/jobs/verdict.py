from __future__ import annotations

import logging
from datetime import datetime, timedelta

from prometheus_client import Counter, Histogram

from apgar.config import Settings
from apgar.domain.models import Agent
from apgar.storage.interfaces import MetaStore
from apgar.storage.types import ReleaseFilters
from apgar.verdict.evaluate import Evaluator

_LOG = logging.getLogger("apgar.jobs")
DURATION = Histogram(
    "apgar_evaluation_duration_seconds",
    "Verdict evaluation duration.",
    ["agent"],
)
EVALUATIONS = Counter(
    "apgar_evaluations_total",
    "Verdict evaluations completed.",
    ["agent", "state"],
)


class VerdictJob:
    def __init__(self, meta_store: MetaStore, evaluator: Evaluator, settings: Settings) -> None:
        self._meta = meta_store
        self._evaluator = evaluator
        self._settings = settings

    async def run(self, now: datetime) -> None:
        agents = await self._meta.list_agents()
        for agent in agents:
            if agent.deleted_at is not None or agent.is_demo:
                continue
            releases = await self._meta.list_releases(
                ReleaseFilters(agent_id=agent.id, final=False, limit=100_000)
            )
            for release in releases:
                if release.final:
                    continue
                if not _due(
                    release.last_seen,
                    release.verdict_updated_at,
                    release.first_seen,
                    now,
                    agent,
                    self._settings,
                ):
                    continue
                try:
                    evaluation = await self._evaluator.evaluate_release(agent, release, now, False)
                except Exception:
                    _LOG.exception(
                        "scheduled evaluation failed",
                        extra={"agent": agent.name, "release": release.release},
                    )
                    continue
                DURATION.labels(agent=agent.name).observe(evaluation.duration_ms / 1000)
                EVALUATIONS.labels(agent=agent.name, state=evaluation.state.value).inc()


IDLE_AFTER = timedelta(hours=24)


def next_check_due(
    last_seen: datetime | None,
    verdict_updated_at: datetime | None,
    first_seen: datetime,
    max_window_hours: int,
    settings: Settings,
    now: datetime,
) -> datetime:
    cap = first_seen + timedelta(hours=max_window_hours)
    if last_seen is None or last_seen < now - IDLE_AFTER:
        return cap
    if verdict_updated_at is None:
        return min(cap, now)
    return min(cap, verdict_updated_at + settings.check_interval(now - first_seen))


def _due(
    last_seen: datetime | None,
    verdict_updated_at: datetime | None,
    first_seen: datetime,
    now: datetime,
    agent: Agent,
    settings: Settings,
) -> bool:
    hours = agent.verdict_settings.max_window_hours
    return next_check_due(last_seen, verdict_updated_at, first_seen, hours, settings, now) <= now
