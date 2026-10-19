from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from apgar.assembly.assembler import Assembler
from apgar.config import Settings
from apgar.demo.generator import DemoSeedError, seed
from apgar.demo.scenarios import BILLING, SUPPORT, release_at
from apgar.domain.enums import SpanStatus
from apgar.domain.models import TurnRow
from apgar.domain.sessions import compute_session_fields
from apgar.normalize.normalizer import HmacKeys
from apgar.storage.memory import InMemoryEventStore, InMemoryMetaStore

_NOW = datetime(2026, 10, 8, 9, 30, tzinfo=UTC)


def _day0(days: int) -> datetime:
    return _NOW - timedelta(days=days)


async def _seed(
    settings: Settings, days: int, turns_per_day: int
) -> tuple[InMemoryEventStore, InMemoryMetaStore, dict[str, Any]]:
    event, meta = InMemoryEventStore(), InMemoryMetaStore()
    assembler = Assembler(event, meta, settings, HmacKeys.from_settings(settings), lambda: _NOW)
    summary = await seed(event, meta, settings, days, turns_per_day, 42, _NOW, assembler)
    return event, meta, summary


def test_deterministic_for_seed() -> None:
    from apgar.demo.scenarios import generate

    first = list(generate(2, 30, 42, _NOW))
    second = list(generate(2, 30, 42, _NOW))
    assert first == second
    other = list(generate(2, 30, 42, _NOW + timedelta(seconds=1)))
    assert [item[1] for item in first] != [item[1] for item in other]


async def test_two_agents_created_with_is_demo(settings: Settings) -> None:
    _event, meta, summary = await _seed(settings, 2, 40)
    agents = await meta.list_agents()
    assert {agent.name for agent in agents} == {BILLING, SUPPORT}
    assert all(agent.is_demo for agent in agents)
    assert set(summary["agents"]) == {BILLING, SUPPORT}


async def test_release_timeline_respected(settings: Settings) -> None:
    event, meta, _summary = await _seed(settings, 2, 80)
    agents = {agent.name: agent.id for agent in await meta.list_agents()}
    day0 = _day0(2)
    for name in (BILLING, SUPPORT):
        turns = [turn for turn in event._turns.values() if turn.agent_id == agents[name]]
        sessions: dict[str, list[TurnRow]] = defaultdict(list)
        for turn in turns:
            sessions[turn.session_id].append(turn)
        for session in sessions.values():
            ordered = sorted(session, key=lambda turn: (turn.start_ts, turn.turn_id))
            if any(turn.release == "untagged" for turn in ordered):
                assert all(turn.release == "untagged" for turn in ordered)
                continue
            start_release = release_at(name, (ordered[0].start_ts - day0).total_seconds() / 86400)
            releases = {turn.release for turn in ordered}
            if releases == {start_release}:
                continue
            for turn in ordered:
                moment = (turn.start_ts - day0).total_seconds() / 86400
                assert turn.release in {start_release, release_at(name, moment)}


async def test_untagged_and_staging_shares(settings: Settings) -> None:
    event, meta, _summary = await _seed(settings, 2, 120)
    agents = {agent.name: agent.id for agent in await meta.list_agents()}
    turns = [turn for turn in event._turns.values() if turn.agent_id == agents[SUPPORT]]
    untagged = sum(1 for turn in turns if turn.release == "untagged") / len(turns)
    staging = sum(1 for turn in turns if turn.environment == "staging") / len(turns)
    assert abs(untagged - 0.08) <= 0.03
    assert abs(staging - 0.03) <= 0.03


async def test_sql_query_error_rate_higher_in_a2(settings: Settings) -> None:
    event, meta, _summary = await _seed(settings, 14, 300)
    agents = {agent.name: agent.id for agent in await meta.list_agents()}
    billing = agents[BILLING]

    def rate(release: str) -> float:
        rows = [
            tool
            for tool in event._tools.values()
            if tool.agent_id == billing
            and tool.release == release
            and tool.tool_name == "sql_query"
        ]
        return sum(1 for tool in rows if tool.status is SpanStatus.error) / len(rows)

    assert rate("fp-8e2f0c6a1b93") >= 0.07
    assert rate("fp-3c1e9a7b2d44") <= 0.035


async def test_long_session_outputs_shorter_in_a3(settings: Settings) -> None:
    event, meta, _summary = await _seed(settings, 14, 300)
    agents = {agent.name: agent.id for agent in await meta.list_agents()}
    turns = [turn for turn in event._turns.values() if turn.agent_id == agents[BILLING]]
    fields = compute_session_fields(turns, _NOW)
    a3 = [turn for turn in turns if turn.release == "fp-5a7d1e3f9c20" and turn.output_tokens]
    long = [
        turn.output_tokens
        for turn in a3
        if fields[turn.turn_id].turn_index > 20 and turn.output_tokens is not None
    ]
    short = [
        turn.output_tokens
        for turn in a3
        if fields[turn.turn_id].turn_index <= 20 and turn.output_tokens is not None
    ]
    assert long and short
    assert sum(long) / len(long) < sum(short) / len(short) * 0.8


async def test_seed_refuses_non_demo_agent(settings: Settings) -> None:
    from tests.factories import make_agent

    event, meta = InMemoryEventStore(), InMemoryMetaStore()
    await meta.upsert_agent(make_agent(_NOW, is_demo=False))
    assembler = Assembler(event, meta, settings, HmacKeys.from_settings(settings), lambda: _NOW)
    with pytest.raises(DemoSeedError, match="billing-copilot"):
        await seed(event, meta, settings, 1, 1, 42, _NOW, assembler)


async def test_reseed_after_later_purge(settings: Settings) -> None:
    from apgar.demo.generator import purge

    event, meta, _summary = await _seed(settings, 1, 20)
    await purge(event, meta, _NOW + timedelta(days=30))
    assert await meta.list_agents() == []
    assembler = Assembler(event, meta, settings, HmacKeys.from_settings(settings), lambda: _NOW)
    summary = await seed(event, meta, settings, 1, 20, 42, _NOW, assembler)
    assert summary["turns"] > 0
    assert {agent.name for agent in await meta.list_agents()} == {BILLING, SUPPORT}


async def test_purge_at_demo_clock_deletes_agents(settings: Settings) -> None:
    from apgar.demo.generator import purge

    # Seeding stamps the agents at wall-clock time, which is after _NOW.
    event, meta, _summary = await _seed(settings, 1, 20)
    await purge(event, meta, _NOW)
    assert await meta.list_agents() == []


async def test_support_behavior_regressions_are_injected(settings: Settings) -> None:
    from apgar.demo.scenarios import _B2, _B3

    event, meta, _summary = await _seed(settings, 14, 300)
    agents = {agent.name: agent for agent in await meta.list_agents()}
    support = agents[SUPPORT]
    turns = [turn for turn in event._turns.values() if turn.agent_id == support.id]

    def loop_share(release: str) -> float:
        known = [
            turn.loop_flag
            for turn in turns
            if turn.release == release and turn.loop_flag is not None
        ]
        return sum(known) / len(known)

    assert loop_share(_B3) >= 0.06 > 0.02 >= loop_share(_B2)
    behavior = {"tool_retry_rate", "loop_rate"}
    assert not behavior & set(support.metric_settings)
    billing = agents[BILLING].metric_settings
    assert all(billing[key] == {"role": "informational"} for key in behavior)


async def test_demo_verdicts_fail_on_behavior_metrics(settings: Settings) -> None:
    import asyncio

    from apgar.demo.generator import simulate_verdicts
    from apgar.verdict.evaluate import Evaluator
    from apgar.verdict.pool import InlinePool

    fast = settings.model_copy(update={"bootstrap_resamples": 300, "bootstrap_chunk": 100})
    event, meta, _summary = await _seed(fast, 14, 300)
    evaluator = Evaluator(event, meta, fast, InlinePool(), lambda: _NOW, [], asyncio.Lock())
    states = await simulate_verdicts(event, meta, fast, _NOW, evaluator, notify=False)
    behavior = ("tool_retry_rate", "loop_rate")
    failing: set[str] = set()
    for agent in await meta.list_agents():
        active: set[str] = set()
        for release in states[agent.name]:
            rows = await meta.list_evaluations(agent.id, release, limit=1)
            items = rows[0].metrics.get("items", {}) if rows else {}
            for metric in behavior:
                item = items.get(metric) or {}
                active |= {metric} if item.get("applicable") else set()
                if item.get("status") == "FAIL" and states[agent.name][release]["state"] == "FAIL":
                    failing.add(metric)
        assert active == set(behavior), agent.name
    assert "loop_rate" in failing
