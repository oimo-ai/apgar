from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from apgar.config import Settings
from apgar.domain.enums import JobRequestKind, ReasonCode, ReleaseEventType, VerdictState
from apgar.domain.models import JobRequest, ReleaseEvent
from apgar.storage.memory import InMemoryEventStore, InMemoryMetaStore
from apgar.verdict.evaluate import Evaluator
from apgar.verdict.pool import InlinePool
from apgar.worker.jobs.handlers import ApplyEventsHandler, DemoSeedHandler, EvaluateHandler
from tests.factories import make_agent, make_release

NOW = datetime(2026, 10, 8, 9, 30, tzinfo=UTC)


def _job(kind: JobRequestKind, payload: dict[str, object]) -> JobRequest:
    return JobRequest("job", "agent-1", "rel", kind, payload, NOW, None, NOW)


async def test_evaluate_skips_demo_agents(settings: Settings) -> None:
    meta = InMemoryMetaStore()
    seen: list[bool] = []

    class _Eval:
        async def evaluate_release(
            self, agent: object, release: object, now: object, manual: bool
        ) -> None:
            _ = (agent, release, now)
            seen.append(manual)

    await meta.upsert_agent(make_agent(NOW, id="agent-1"))
    await meta.upsert_release(make_release(NOW, agent_id="agent-1", release="rel"))
    handler = EvaluateHandler(_Eval(), meta)  # type: ignore[arg-type]
    await handler.handle(_job(JobRequestKind.evaluate, {}), NOW)
    assert seen == [False]
    await meta.upsert_agent(
        make_agent(NOW, id="agent-1", is_demo=True, updated_at=NOW + timedelta(seconds=1))
    )
    await handler.handle(_job(JobRequestKind.evaluate, {}), NOW)
    assert seen == [False]


async def test_apply_events_evaluates_once_per_change(settings: Settings) -> None:
    _ = settings
    meta = InMemoryMetaStore()
    await meta.upsert_agent(make_agent(NOW, id="agent-1", name="billing-copilot"))
    earlier = NOW - timedelta(minutes=10)
    await meta.upsert_release(
        make_release(
            NOW,
            agent_id="agent-1",
            release="rel",
            state=VerdictState.FAIL,
            reason=ReasonCode.confirmed,
            verdict_updated_at=earlier,
        )
    )
    seen: list[bool] = []

    class _Eval:
        async def evaluate_release(
            self, agent: object, release: object, now: object, manual: bool
        ) -> None:
            _ = (agent, release, now)
            seen.append(manual)

    handler = ApplyEventsHandler(_Eval(), meta)  # type: ignore[arg-type]
    await meta.append_release_event(
        ReleaseEvent("agent-1", "rel", earlier, ReleaseEventType.expected_changes, {}, "")
    )
    await handler.handle(_job(JobRequestKind.apply_events, {}), NOW)
    assert seen == []
    for kind in (ReleaseEventType.stop, ReleaseEventType.manual_baseline):
        await meta.append_release_event(ReleaseEvent("agent-1", "rel", NOW, kind, {}, ""))
    await handler.handle(_job(JobRequestKind.apply_events, {}), NOW)
    assert seen == [True]


async def test_demo_seed_calls_seed_and_simulate(settings: Settings, monkeypatch: object) -> None:
    called: list[str] = []

    async def _seed(*args: object, **kwargs: object) -> None:
        _ = (args, kwargs)
        called.append("seed")

    async def _simulate(*args: object, **kwargs: object) -> dict[str, str]:
        _ = (args, kwargs)
        called.append("simulate")
        return {}

    monkeypatch.setattr("apgar.demo.generator.seed", _seed)  # type: ignore[attr-defined]
    monkeypatch.setattr("apgar.demo.generator.simulate_verdicts", _simulate)  # type: ignore[attr-defined]
    meta = InMemoryMetaStore()
    events = InMemoryEventStore()
    evaluator = Evaluator(events, meta, settings, InlinePool(), lambda: NOW, [], asyncio.Lock())
    handler = DemoSeedHandler(events, meta, settings, evaluator)
    job = JobRequest("job", "", "", JobRequestKind.demo_seed, {}, NOW, None, NOW)
    await handler.handle(job, NOW)
    assert called == ["seed", "simulate"]
