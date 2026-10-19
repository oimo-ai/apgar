from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import cast

from apgar.config import Settings
from apgar.domain.enums import ReasonCode, VerdictState
from apgar.domain.models import Agent, Release
from apgar.verdict.evaluate import Evaluator
from apgar.worker.jobs.finalize import FinalizeJob
from apgar.worker.jobs.verdict import _due
from tests.factories import make_agent, make_release
from tests.support import MemStores

NOW = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)


class _Recorder:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def evaluate_release(
        self, agent: Agent, release: Release, now: datetime, manual: bool
    ) -> None:
        _ = (agent, now, manual)
        self.calls.append(release.release)


async def test_finalize_evaluates_taken_over_and_elapsed_releases(
    mem_stores: MemStores,
) -> None:
    _events, meta = mem_stores
    agent = make_agent(NOW)
    await meta.upsert_agent(agent)
    releases = {
        "old": NOW - timedelta(hours=10),
        "expired": NOW - timedelta(hours=80),
        "done": NOW - timedelta(hours=20),
        "new": NOW - timedelta(hours=1),
    }
    for name, seen in releases.items():
        await meta.upsert_release(
            make_release(
                seen,
                agent_id=agent.id,
                release=name,
                first_seen=seen,
                state=VerdictState.INCONCLUSIVE,
                reason=ReasonCode.insufficient_power,
                final=name == "done",
            )
        )
    recorder = _Recorder()
    await FinalizeJob(meta, cast(Evaluator, recorder)).run(NOW)
    assert sorted(recorder.calls) == ["expired", "old"]


def test_due_uses_early_cadence_then_regular(settings: Settings) -> None:
    agent = make_agent(NOW)
    young = NOW - timedelta(minutes=30)
    seen = NOW - timedelta(minutes=1)
    assert _due(seen, NOW - timedelta(minutes=6), young, NOW, agent, settings)
    assert not _due(seen, NOW - timedelta(minutes=4), young, NOW, agent, settings)
    older = NOW - timedelta(hours=5)
    assert not _due(seen, NOW - timedelta(minutes=6), older, NOW, agent, settings)
    assert _due(seen, NOW - timedelta(minutes=16), older, NOW, agent, settings)
    assert settings.check_interval(timedelta(hours=1)) == timedelta(minutes=5)
    assert settings.check_interval(timedelta(hours=3)) == timedelta(minutes=15)
