from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import timedelta

from apgar.config import Settings
from apgar.domain.enums import (
    MetricId,
    OutputFormat,
    ReasonCode,
    ReleaseEventType,
    VerdictState,
)
from apgar.domain.models import ReleaseEvent, VerdictEvaluation
from apgar.storage.memory import InMemoryEventStore, InMemoryMetaStore
from apgar.storage.types import ArmData, ArmQuery
from apgar.verdict.evaluate import Evaluator
from apgar.verdict.pool import InlinePool
from tests.factories import make_evaluation
from tests.unit.test_evaluate_core import NOW, _agent, _seed, _settings, _turn

_KEYS = {
    "agent",
    "release",
    "verdict",
    "reason",
    "final",
    "ok",
    "baseline",
    "sample",
    "excluded",
    "window",
    "evaluated_at",
    "failed_metrics",
    "report_url",
}


def _evaluator(event: InMemoryEventStore, meta: InMemoryMetaStore, settings: Settings) -> Evaluator:
    return Evaluator(
        event, meta, _settings(settings), InlinePool(), lambda: NOW, [], asyncio.Lock()
    )


async def test_no_baseline_pending(settings: Settings) -> None:
    event, meta = InMemoryEventStore(), InMemoryMetaStore()
    await _seed(meta, event, 0.0)
    agent = await meta.get_agent("agent-1")
    base = await meta.get_release("agent-1", "base")
    assert agent is not None and base is not None
    result = await _evaluator(event, meta, settings).evaluate_release(
        agent, base, base.first_seen + timedelta(hours=2), False
    )
    assert result is not None
    assert result.state is VerdictState.PENDING
    assert result.reason is ReasonCode.no_baseline


async def test_insufficient_sample_turns_needed(settings: Settings) -> None:
    event, meta = InMemoryEventStore(), InMemoryMetaStore()
    await _seed(meta, event, 0.0)
    agent = await meta.get_agent("agent-1")
    assert agent is not None
    extra = []
    for index in range(10):
        turn, tool = _turn("tiny", index, index, error=False, start=NOW - timedelta(hours=20))
        extra.append((turn, tool))
    from apgar.worker.jobs.release_discovery import new_release

    await meta.upsert_release(
        new_release("agent-1", "tiny", NOW - timedelta(hours=20), ReasonCode.no_baseline, NOW)
    )
    await event.upsert_turns([turn for turn, _tool in extra])
    await event.insert_tool_calls([tool for _turn_row, tool in extra])
    release = await meta.get_release("agent-1", "tiny")
    assert release is not None
    result = await _evaluator(event, meta, settings).evaluate_release(agent, release, NOW, False)
    assert result is not None
    assert result.reason is ReasonCode.insufficient_sample
    assert result.metrics["sample"]["turns_needed"] == 30


async def test_insufficient_baseline(settings: Settings) -> None:
    event, meta = InMemoryEventStore(), InMemoryMetaStore()
    agent = _agent(NOW)
    await meta.upsert_agent(agent)
    from apgar.worker.jobs.release_discovery import new_release

    base_start = NOW - timedelta(days=3)
    cand_start = NOW - timedelta(hours=30)
    await meta.upsert_release(
        new_release("agent-1", "base", base_start, ReasonCode.no_baseline, base_start)
    )
    await meta.upsert_release(
        new_release("agent-1", "cand", cand_start, ReasonCode.insufficient_sample, cand_start)
    )
    turns = []
    tools = []
    for index in range(5):
        turn, tool = _turn("base", index, index // 2, error=False, start=base_start)
        turns.append(turn)
        tools.append(tool)
    for index in range(80):
        turn, tool = _turn("cand", index, index // 5, error=False, start=cand_start)
        turns.append(turn)
        tools.append(tool)
    await event.upsert_turns(turns)
    await event.insert_tool_calls(tools)
    release = await meta.get_release("agent-1", "cand")
    assert release is not None
    result = await _evaluator(event, meta, settings).evaluate_release(agent, release, NOW, False)
    assert result is not None
    assert result.reason is ReasonCode.insufficient_baseline


async def test_baseline_needs_the_minimum_sessions_too(settings: Settings) -> None:
    event, meta = InMemoryEventStore(), InMemoryMetaStore()
    agent = _agent(NOW)
    await meta.upsert_agent(agent)
    from apgar.worker.jobs.release_discovery import new_release

    base_start = NOW - timedelta(days=3)
    cand_start = NOW - timedelta(hours=30)
    await meta.upsert_release(
        new_release("agent-1", "base", base_start, ReasonCode.no_baseline, base_start)
    )
    await meta.upsert_release(
        new_release("agent-1", "cand", cand_start, ReasonCode.insufficient_sample, cand_start)
    )
    vs = agent.verdict_settings
    rows = [
        _turn("base", index, index % 2, error=False, start=base_start)
        for index in range(vs.min_turns + 10)
    ] + [_turn("cand", index, index // 5, error=False, start=cand_start) for index in range(80)]
    await event.upsert_turns([turn for turn, _tool in rows])
    await event.insert_tool_calls([tool for _turn_row, tool in rows])
    release = await meta.get_release("agent-1", "cand")
    assert release is not None
    result = await _evaluator(event, meta, settings).evaluate_release(agent, release, NOW, False)
    assert result is not None
    assert (result.state, result.reason) == (VerdictState.PENDING, ReasonCode.insufficient_baseline)
    assert result.n_baseline_turns == vs.min_turns + 10
    assert result.n_baseline_sessions == 2


async def test_mixed_sessions_are_counted_as_excluded(settings: Settings) -> None:
    event, meta = InMemoryEventStore(), InMemoryMetaStore()
    await _seed(meta, event, 0.0)
    agent = await meta.get_agent("agent-1")
    release = await meta.get_release("agent-1", "cand")
    assert agent is not None and release is not None
    shared = []
    cand_start = NOW - timedelta(hours=30)
    for index in range(40):
        session = index // 5
        start = cand_start + timedelta(minutes=session * 5)
        turn, tool = _turn("base", 0, 0, error=False, start=start)
        turn.session_id = f"cand-s{session}"
        turn.turn_id = f"0{index:04d}"
        turn.trace_id = f"{9000 + index:032x}"
        tool.session_id = turn.session_id
        tool.turn_id = turn.turn_id
        tool.tool_call_id = f"tool-{turn.turn_id}"
        shared.append((turn, tool))
    await event.upsert_turns([turn for turn, _tool in shared])
    await event.insert_tool_calls([tool for _turn, tool in shared])
    result = await _evaluator(event, meta, settings).evaluate_release(agent, release, NOW, False)
    assert result is not None
    assert result.n_excluded_mixed > 0


async def test_fail_after_two_evaluations(settings: Settings) -> None:
    event, meta = InMemoryEventStore(), InMemoryMetaStore()
    await _seed(meta, event, 0.4)
    agent = await meta.get_agent("agent-1")
    release = await meta.get_release("agent-1", "cand")
    assert agent is not None and release is not None
    evaluator = _evaluator(event, meta, settings)
    first = await evaluator.evaluate_release(agent, release, NOW - timedelta(minutes=20), False)
    assert first is not None
    assert first.reason is ReasonCode.fail_candidate
    stored = await meta.get_release("agent-1", "cand")
    assert stored is not None
    second = await evaluator.evaluate_release(agent, stored, NOW, False)
    assert second is not None
    assert second.state is VerdictState.FAIL
    assert second.reason is ReasonCode.confirmed


async def test_pass_after_two_evaluations_equal_arms(settings: Settings) -> None:
    event, meta = InMemoryEventStore(), InMemoryMetaStore()
    await _seed(meta, event, 0.0)
    agent = await meta.get_agent("agent-1")
    release = await meta.get_release("agent-1", "cand")
    assert agent is not None and release is not None
    evaluator = _evaluator(event, meta, settings)
    await evaluator.evaluate_release(agent, release, NOW - timedelta(minutes=20), False)
    stored = await meta.get_release("agent-1", "cand")
    assert stored is not None
    second = await evaluator.evaluate_release(agent, stored, NOW, False)
    assert second is not None
    assert second.state is VerdictState.PASS


async def test_expected_changes_excluded(settings: Settings) -> None:
    event, meta = InMemoryEventStore(), InMemoryMetaStore()
    await _seed(meta, event, 0.4)
    agent = await meta.get_agent("agent-1")
    release = await meta.get_release("agent-1", "cand")
    assert agent is not None and release is not None
    await meta.append_release_event(
        ReleaseEvent(
            "agent-1",
            "cand",
            NOW - timedelta(minutes=1),
            ReleaseEventType.expected_changes,
            {"metrics": [MetricId.tool_error_rate.value]},
            "",
        )
    )
    result = await _evaluator(event, meta, settings).evaluate_release(agent, release, NOW, False)
    assert result is not None
    item = result.metrics["items"]["tool_error_rate"]
    assert item["status"] == "EXPECTED"
    guard = result.metrics["guard_count"]
    assert result.metrics["alpha_adjusted"] == agent.verdict_settings.alpha / guard


async def test_informational_not_in_guard(settings: Settings) -> None:
    event, meta = InMemoryEventStore(), InMemoryMetaStore()
    await _seed(meta, event, 0.4)
    agent = await meta.get_agent("agent-1")
    assert agent is not None
    agent.metric_settings = {"tool_error_rate": {"role": "informational"}}
    release = await meta.get_release("agent-1", "cand")
    assert release is not None
    result = await _evaluator(event, meta, settings).evaluate_release(agent, release, NOW, False)
    assert result is not None
    assert result.metrics["items"]["tool_error_rate"]["role"] == "informational"
    assert result.metrics["any_fail"] is False


async def test_final_window_elapsed(settings: Settings) -> None:
    event, meta = InMemoryEventStore(), InMemoryMetaStore()
    await _seed(meta, event, 0.0)
    agent = await meta.get_agent("agent-1")
    base = await meta.get_release("agent-1", "base")
    assert agent is not None and base is not None
    result = await _evaluator(event, meta, settings).evaluate_release(
        agent, base, base.first_seen + timedelta(hours=73), False
    )
    assert result is not None
    assert result.state is VerdictState.INCONCLUSIVE
    assert result.reason is ReasonCode.window_elapsed
    assert result.final is True
    assert result.metrics["ended"] == {"reason": "window_elapsed", "by": None}


async def test_takeover_ends_monitoring(settings: Settings) -> None:
    event, meta = InMemoryEventStore(), InMemoryMetaStore()
    await _seed(meta, event, 0.0)
    agent = await meta.get_agent("agent-1")
    base = await meta.get_release("agent-1", "base")
    assert agent is not None and base is not None
    when = NOW - timedelta(hours=29)
    result = await _evaluator(event, meta, settings).evaluate_release(agent, base, when, False)
    assert result is not None
    assert (result.state, result.reason, result.final) == (
        VerdictState.INCONCLUSIVE,
        ReasonCode.superseded,
        True,
    )
    assert result.metrics["ended"] == {"reason": "superseded", "by": "cand"}


async def _failed(settings: Settings) -> tuple[InMemoryEventStore, InMemoryMetaStore, Evaluator]:
    event, meta = InMemoryEventStore(), InMemoryMetaStore()
    await _seed(meta, event, 0.4)
    agent = await meta.get_agent("agent-1")
    release = await meta.get_release("agent-1", "cand")
    assert agent is not None and release is not None
    evaluator = _evaluator(event, meta, settings)
    await evaluator.evaluate_release(agent, release, NOW - timedelta(minutes=20), False)
    stored = await meta.get_release("agent-1", "cand")
    assert stored is not None
    result = await evaluator.evaluate_release(agent, stored, NOW, False)
    assert result is not None and result.state is VerdictState.FAIL
    return event, meta, evaluator


def _expected(at: object) -> ReleaseEvent:
    return ReleaseEvent(
        "agent-1",
        "cand",
        at,  # type: ignore[arg-type]
        ReleaseEventType.expected_changes,
        {"metrics": [MetricId.tool_error_rate.value]},
        "",
    )


async def test_fail_holds_without_a_change(settings: Settings) -> None:
    _event, meta, evaluator = await _failed(settings)
    agent = await meta.get_agent("agent-1")
    stored = await meta.get_release("agent-1", "cand")
    assert agent is not None and stored is not None
    result = await evaluator.evaluate_release(agent, stored, NOW + timedelta(minutes=20), True)
    assert result is not None
    assert (result.state, result.reason) == (VerdictState.FAIL, ReasonCode.confirmed)


async def test_expected_change_reopens_fail(settings: Settings) -> None:
    _event, meta, evaluator = await _failed(settings)
    await meta.append_release_event(_expected(NOW + timedelta(minutes=1)))
    agent = await meta.get_agent("agent-1")
    stored = await meta.get_release("agent-1", "cand")
    assert agent is not None and stored is not None
    result = await evaluator.evaluate_release(agent, stored, NOW + timedelta(minutes=2), True)
    assert result is not None
    assert result.state is VerdictState.INCONCLUSIVE
    assert result.metrics["items"]["tool_error_rate"]["status"] == "EXPECTED"


async def test_stop_ends_monitoring_at_the_stop(settings: Settings) -> None:
    event, meta = InMemoryEventStore(), InMemoryMetaStore()
    await _seed(meta, event, 0.0)
    agent = await meta.get_agent("agent-1")
    release = await meta.get_release("agent-1", "cand")
    assert agent is not None and release is not None
    stopped = NOW - timedelta(hours=1)
    await meta.append_release_event(
        ReleaseEvent("agent-1", "cand", stopped, ReleaseEventType.stop, {}, "sam")
    )
    result = await _evaluator(event, meta, settings).evaluate_release(agent, release, NOW, True)
    assert result is not None
    assert result.final is True
    assert result.window_end == stopped
    assert result.metrics["ended"] == {"reason": "stopped", "by": None}


async def test_summary_matches_appendix_f(settings: Settings) -> None:
    event, meta = InMemoryEventStore(), InMemoryMetaStore()
    await _seed(meta, event, 0.0)
    agent = await meta.get_agent("agent-1")
    base = await meta.get_release("agent-1", "base")
    assert agent is not None and base is not None
    await _evaluator(event, meta, settings).evaluate_release(
        agent, base, base.first_seen + timedelta(hours=2), False
    )
    stored = await meta.get_release("agent-1", "base")
    assert stored is not None
    assert set(stored.verdict_summary) >= _KEYS
    assert stored.verdict_summary["ok"] is None
    assert stored.verdict_summary["report_url"].startswith("http://localhost:8080/agents/")


async def test_headline_metric_and_power_statements(settings: Settings) -> None:
    event, meta = InMemoryEventStore(), InMemoryMetaStore()
    await _seed(meta, event, 0.0)
    agent = await meta.get_agent("agent-1")
    release = await meta.get_release("agent-1", "cand")
    assert agent is not None and release is not None
    result = await _evaluator(event, meta, settings).evaluate_release(agent, release, NOW, False)
    assert result is not None
    items = result.metrics["items"]
    ratios = {
        key: abs(item["detectable_degradation"]) / item["tolerance"]
        for key, item in items.items()
        if item["role"] == "guardrail" and item["detectable_degradation"] is not None
    }
    assert result.metrics["headline_metric"] == max(ratios, key=lambda key: ratios[key])
    item = items["tool_error_rate"]
    assert "turns_needed" in item
    assert "detectable_degradation" in item


async def test_mixed_sessions_excluded(settings: Settings) -> None:
    event, meta = InMemoryEventStore(), InMemoryMetaStore()
    await _seed(meta, event, 0.0)
    agent = await meta.get_agent("agent-1")
    release = await meta.get_release("agent-1", "cand")
    assert agent is not None and release is not None
    shared = []
    for index in range(8):
        turn, tool = _turn("base", 2000 + index, 0, error=False, start=NOW - timedelta(days=3))
        turn.session_id = f"cand-s{index // 5}"
        tool.session_id = turn.session_id
        shared.append((turn, tool))
    await event.upsert_turns([turn for turn, _tool in shared])
    await event.insert_tool_calls([tool for _turn, tool in shared])
    result = await _evaluator(event, meta, settings).evaluate_release(agent, release, NOW, False)
    assert result is not None
    assert result.n_excluded_mixed > 0
    assert "mixed_stratum" not in result.metrics


async def test_trend_field(settings: Settings) -> None:
    event, meta = InMemoryEventStore(), InMemoryMetaStore()
    await _seed(meta, event, 0.4)
    agent = await meta.get_agent("agent-1")
    release = await meta.get_release("agent-1", "cand")
    assert agent is not None and release is not None
    prior = make_evaluation(
        NOW - timedelta(hours=1),
        agent_id="agent-1",
        release="cand",
        metrics={
            "items": {"tool_error_rate": {"delta": 0.0, "status": "PASS", "role": "guardrail"}}
        },
    )
    await meta.append_evaluation(prior)
    result = await _evaluator(event, meta, settings).evaluate_release(agent, release, NOW, False)
    assert result is not None
    assert result.metrics["items"]["tool_error_rate"]["trend"] == "worsening"


async def test_agent_without_tools_verdict_from_remaining_metrics(settings: Settings) -> None:
    event, meta = InMemoryEventStore(), InMemoryMetaStore()
    agent = replace(_agent(NOW), output_format=OutputFormat.json)
    await meta.upsert_agent(agent)
    from apgar.worker.jobs.release_discovery import new_release

    base_start = NOW - timedelta(days=3)
    cand_start = NOW - timedelta(hours=30)
    await meta.upsert_release(
        new_release("agent-1", "base", base_start, ReasonCode.no_baseline, base_start)
    )
    await meta.upsert_release(
        new_release("agent-1", "cand", cand_start, ReasonCode.insufficient_sample, cand_start)
    )
    turns = []
    for name, start in (("base", base_start), ("cand", cand_start)):
        for index in range(80):
            turn, _tool = _turn(name, index, index // 5, error=False, start=start)
            turn.tool_calls = 0
            turn.tool_errors = 0
            turn.zero_tool_flag = True
            turn.format_ok = True
            turns.append(turn)
    await event.upsert_turns(turns)
    release = await meta.get_release("agent-1", "cand")
    assert release is not None
    result = await _evaluator(event, meta, settings).evaluate_release(agent, release, NOW, False)
    assert result is not None
    for metric in (
        "tool_error_rate",
        "tool_retry_rate",
        "tool_calls_per_turn",
        "zero_tool_turn_rate",
    ):
        assert result.metrics["items"][metric]["na_reason"] == "no_tools"
    assert result.metrics["guard_count"] == 6


class _ChangeDuringArmLoad(InMemoryEventStore):
    def __init__(self, meta: InMemoryMetaStore) -> None:
        super().__init__()
        self.meta = meta
        self.armed = False
        self.injected = False

    async def load_arm(self, query: ArmQuery) -> ArmData:
        arm = await super().load_arm(query)
        if self.armed and not self.injected and query.release == "cand":
            self.injected = True
            await self.meta.append_release_event(_expected(NOW + timedelta(minutes=3)))
        return arm


async def test_change_during_evaluation_reopens_on_the_next_one(
    settings: Settings,
) -> None:
    meta = InMemoryMetaStore()
    event = _ChangeDuringArmLoad(meta)
    await _seed(meta, event, 0.4)
    agent = await meta.get_agent("agent-1")
    release = await meta.get_release("agent-1", "cand")
    assert agent is not None and release is not None
    evaluator = _evaluator(event, meta, settings)
    await evaluator.evaluate_release(agent, release, NOW - timedelta(minutes=20), False)
    stored = await meta.get_release("agent-1", "cand")
    assert stored is not None
    await evaluator.evaluate_release(agent, stored, NOW, False)
    stored = await meta.get_release("agent-1", "cand")
    assert stored is not None and stored.state is VerdictState.FAIL
    event.armed = True
    result = await evaluator.evaluate_release(agent, stored, NOW + timedelta(minutes=2), False)
    assert event.injected
    assert result is not None
    assert result.state is VerdictState.FAIL
    stored = await meta.get_release("agent-1", "cand")
    assert stored is not None
    result = await evaluator.evaluate_release(agent, stored, NOW + timedelta(minutes=4), True)
    assert result is not None
    assert result.state is VerdictState.INCONCLUSIVE


async def _early_result(settings: Settings, error_rate: float) -> object:
    event, meta = InMemoryEventStore(), InMemoryMetaStore()
    await _seed(meta, event, error_rate)
    extra = [
        _turn("base", index, index, error=False, start=NOW - timedelta(days=3))
        for index in range(80, 100)
    ]
    await event.upsert_turns([turn for turn, _tool in extra])
    await event.insert_tool_calls([tool for _turn_row, tool in extra])
    agent = await meta.get_agent("agent-1")
    release = await meta.get_release("agent-1", "cand")
    assert agent is not None and release is not None
    vs = agent.verdict_settings.model_copy(update={"min_sessions": 30})
    agent = replace(agent, verdict_settings=vs)
    await meta.upsert_agent(agent)
    return await _evaluator(event, meta, settings).evaluate_release(agent, release, NOW, False)


async def test_early_failure_leaves_pending_below_minimum(settings: Settings) -> None:
    result = await _early_result(settings, 0.9)
    assert isinstance(result, VerdictEvaluation)
    assert (result.state, result.reason) == (VerdictState.INCONCLUSIVE, ReasonCode.fail_candidate)
    assert result.metrics["early"] is True
    assert result.metrics["items"]["tool_error_rate"]["status"] == "FAIL"


async def test_calm_early_sample_stays_collecting_with_raw_values(settings: Settings) -> None:
    result = await _early_result(settings, 0.0)
    assert isinstance(result, VerdictEvaluation)
    assert (result.state, result.reason) == (VerdictState.PENDING, ReasonCode.insufficient_sample)
    assert result.metrics["early"] is False
    assert result.metrics["any_fail"] is False
    assert result.metrics["items"]["tool_error_rate"]["candidate"] == 0.0
