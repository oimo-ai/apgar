from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime, timedelta

import pytest

from apgar.actions.dispatcher import TransitionEmitter
from apgar.config import Settings
from apgar.domain.enums import (
    ConnectionType,
    NotificationChannel,
    NotificationEvent,
    ReasonCode,
    VerdictState,
)
from apgar.domain.models import Agent, Release, VerdictEvaluation
from apgar.storage.memory import InMemoryEventStore, InMemoryMetaStore
from apgar.verdict.coverage import metric_coverage
from apgar.verdict.evaluate import Evaluator, TransitionEvent, end_of_monitoring
from apgar.verdict.pool import InlinePool
from apgar.worker.jobs.release_discovery import new_release
from tests.factories import make_connection, make_evaluation, make_release
from tests.unit.test_evaluate_core import NOW, _seed, _settings, _turn

CAND_START = NOW - timedelta(hours=30)


def _evaluator(
    event: InMemoryEventStore,
    meta: InMemoryMetaStore,
    settings: Settings,
    hooks: list[object] | None = None,
) -> Evaluator:
    return Evaluator(
        event,
        meta,
        _settings(settings),
        InlinePool(),
        lambda: NOW,
        list(hooks or []),  # type: ignore[arg-type]
        asyncio.Lock(),
    )


async def _stores(
    error_rate: float, **verdict: int
) -> tuple[InMemoryEventStore, InMemoryMetaStore]:
    event, meta = InMemoryEventStore(), InMemoryMetaStore()
    await _seed(meta, event, error_rate)
    agent = await meta.get_agent("agent-1")
    assert agent is not None
    if verdict:
        vs = agent.verdict_settings.model_copy(update=verdict)
        await meta.upsert_agent(replace(agent, verdict_settings=vs))
    return event, meta


async def _load(meta: InMemoryMetaStore, release: str) -> tuple[Agent, Release]:
    agent = await meta.get_agent("agent-1")
    row = await meta.get_release("agent-1", release)
    assert agent is not None and row is not None
    return agent, row


async def _add_release(
    meta: InMemoryMetaStore,
    event: InMemoryEventStore,
    release: str,
    start: datetime,
    count: int,
    environment: str = "production",
) -> None:
    await meta.upsert_release(new_release("agent-1", release, start, ReasonCode.no_baseline, start))
    await _add_turns(event, release, start, count, environment)


async def _add_turns(
    event: InMemoryEventStore,
    release: str,
    start: datetime,
    count: int,
    environment: str = "production",
    tag: str = "x",
) -> None:
    rows = [_turn(release, index, index // 5, error=False, start=start) for index in range(count)]
    for turn, tool in rows:
        turn.environment = environment
        turn.turn_id = tool.turn_id = f"{tag}{turn.turn_id}"
        tool.tool_call_id = f"tool-{turn.turn_id}"
        turn.session_id = tool.session_id = f"{tag}{turn.session_id}"
        turn.trace_id = f"{tag}{release}{turn.trace_id}"[-32:]
    await event.upsert_turns([turn for turn, _tool in rows])
    await event.insert_tool_calls([tool for _turn_row, tool in rows])


async def test_first_release_has_coverage_and_raw_values(settings: Settings) -> None:
    event, meta = await _stores(0.0)
    agent, base = await _load(meta, "base")
    result = await _evaluator(event, meta, settings).evaluate_release(
        agent, base, base.first_seen + timedelta(hours=2), False
    )
    assert result is not None and result.reason is ReasonCode.no_baseline
    item = result.metrics["items"]["tool_error_rate"]
    assert (item["applicable"], item["candidate"], item["baseline"]) == (True, 0.0, None)
    coverage = metric_coverage(agent, result.metrics["items"])
    assert coverage is not None and coverage["active"] > 0


async def test_below_floor_has_coverage(settings: Settings) -> None:
    event, meta = InMemoryEventStore(), InMemoryMetaStore()
    await _seed(meta, event, 0.0)
    await _add_release(meta, event, "tiny", NOW - timedelta(hours=20), 10)
    agent, release = await _load(meta, "tiny")
    result = await _evaluator(event, meta, settings).evaluate_release(agent, release, NOW, False)
    assert result is not None and result.reason is ReasonCode.insufficient_sample
    item = result.metrics["items"]["tool_error_rate"]
    assert (item["applicable"], item["status"], item["candidate"]) == (True, "INCONCLUSIVE", 0.0)


async def test_release_flow_detects_then_confirms_a_regression(
    settings: Settings,
) -> None:
    event, meta = await _stores(0.9)
    slack = make_connection(
        NOW,
        id="slack-1",
        name="slack",
        type=ConnectionType.slack,
        config={"webhook_url": "https://hooks.slack.com/services/T/B/x"},
    )
    await meta.upsert_connection(slack)
    agent, cand = await _load(meta, "cand")
    agent = replace(agent, slack_connection_id=slack.id)
    await meta.upsert_agent(agent)
    emitter = TransitionEmitter(meta, settings, lambda: NOW)
    await emitter.on_registered(agent, cand)

    async def emit(ev: TransitionEvent) -> None:
        await emitter.on_transition(ev)

    evaluator = _evaluator(event, meta, settings, [emit])
    first = await evaluator.evaluate_release(agent, cand, NOW - timedelta(minutes=20), False)
    assert first is not None and first.reason is ReasonCode.fail_candidate
    _agent_row, cand = await _load(meta, "cand")
    second = await evaluator.evaluate_release(agent, cand, NOW, False)
    assert second is not None
    assert (second.state, second.reason) == (VerdictState.FAIL, ReasonCode.confirmed)

    rows = await meta.list_notifications(None, limit=50)
    slack_events = [row.event for row in rows if row.channel is NotificationChannel.slack]
    assert slack_events.count(NotificationEvent.release_detected) == 1
    assert NotificationEvent.regression in slack_events


async def test_takeover_confirms_a_pending_regression(settings: Settings) -> None:
    event, meta = await _stores(0.9, fail_confirmations=3)
    await _add_turns(event, "base", CAND_START - timedelta(days=1), 80)
    agent, cand = await _load(meta, "cand")
    evaluator = _evaluator(event, meta, settings)
    first = await evaluator.evaluate_release(agent, cand, CAND_START + timedelta(minutes=65), False)
    assert first is not None and first.reason is ReasonCode.fail_candidate
    await _add_release(meta, event, "next", CAND_START + timedelta(minutes=80), 60)
    _agent_row, cand = await _load(meta, "cand")
    final = await evaluator.evaluate_release(
        agent, cand, CAND_START + timedelta(minutes=140), False
    )
    assert final is not None
    assert (final.state, final.reason, final.final) == (
        VerdictState.FAIL,
        ReasonCode.confirmed,
        True,
    )
    assert final.metrics["ended"] == {"reason": "superseded", "by": "next"}


@pytest.mark.parametrize(("baseline", "expected"), [("base", "FAIL"), ("older", "INCONCLUSIVE")])
async def test_baseline_change_restarts_confirmation(
    settings: Settings, baseline: str, expected: str
) -> None:
    event, meta = await _stores(0.9)
    agent, cand = await _load(meta, "cand")
    cand = replace(cand, state=VerdictState.INCONCLUSIVE, reason=ReasonCode.fail_candidate)
    await meta.upsert_release(cand)
    prior: VerdictEvaluation = make_evaluation(
        NOW - timedelta(minutes=20),
        agent_id="agent-1",
        release="cand",
        baseline_release=baseline,
        state=VerdictState.INCONCLUSIVE,
        reason=ReasonCode.fail_candidate,
        metrics={"any_fail": True, "all_pass": False},
    )
    await meta.append_evaluation(prior)
    result = await _evaluator(event, meta, settings).evaluate_release(agent, cand, NOW, False)
    assert result is not None and result.baseline_release == "base"
    assert result.state.value == expected


async def test_clean_ended_release_becomes_the_next_baseline(settings: Settings) -> None:
    event, meta = await _stores(0.0)
    agent, cand = await _load(meta, "cand")
    cand = replace(cand, state=VerdictState.INCONCLUSIVE, reason=ReasonCode.superseded, final=True)
    await meta.upsert_release(cand)
    await _add_release(meta, event, "next", NOW - timedelta(hours=20), 80)
    _agent_row, nxt = await _load(meta, "next")
    result = await _evaluator(event, meta, settings).evaluate_release(agent, nxt, NOW, False)
    assert result is not None
    assert (result.baseline_release, result.baseline_mode) == ("cand", "previous_release")


async def test_release_activity_ignores_other_environments() -> None:
    event, meta = await _stores(0.0)
    await _add_release(meta, event, "next", CAND_START, 80, "staging")
    await _add_turns(event, "next", CAND_START + timedelta(seconds=30), 80, "staging", "y")
    scoped = await event.release_activity("agent-1", "production")
    assert {row.release for row in scoped} == {"base", "cand"}


def test_end_of_monitoring_rules() -> None:
    release = make_release(CAND_START, agent_id="agent-1", release="cand")
    older = make_release(CAND_START - timedelta(days=2), agent_id="agent-1", release="base")
    later = make_release(CAND_START + timedelta(hours=2), agent_id="agent-1", release="later")
    newer = make_release(CAND_START + timedelta(hours=1), agent_id="agent-1", release="next")
    untagged = make_release(CAND_START + timedelta(hours=1), agent_id="agent-1", release="untagged")
    future = make_release(NOW + timedelta(minutes=1), agent_id="agent-1", release="future")
    cap = NOW + timedelta(days=1)
    assert end_of_monitoring(release, [release, older, untagged, future], NOW, cap) is None
    ended = end_of_monitoring(release, [release, older, later, newer], NOW, cap)
    assert ended is not None
    assert (ended.reason, ended.by) == (ReasonCode.superseded, "next")
    elapsed = end_of_monitoring(release, [release], cap, cap)
    assert elapsed is not None and elapsed.reason is ReasonCode.window_elapsed
