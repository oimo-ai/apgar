from __future__ import annotations

from dataclasses import replace

from apgar.domain.enums import MetricId
from apgar.storage.types import ArmTurn
from apgar.verdict.applicability import assess
from apgar.verdict.metrics import MetricSpec, default_specs
from tests.unit.test_metrics import tool, turn


def _spec(metric: MetricId, **updates: object) -> MetricSpec:
    found = next(item for item in default_specs() if item.id is metric)
    if not updates:
        return found
    return replace(found, settings=found.settings.model_copy(update=updates))


def _turns(count: int, **overrides: object) -> list[ArmTurn]:
    return [turn(index, session_id=f"s{index}", **overrides) for index in range(count)]


def test_disabled() -> None:
    spec = _spec(MetricId.llm_error_rate, enabled=False)
    rows = _turns(2)
    decision = assess(spec, rows, [], rows, [])
    assert decision.applicable is False
    assert decision.na_reason == "disabled"


def test_no_tools_when_baseline_has_none() -> None:
    spec = _spec(MetricId.tool_error_rate)
    per_turn = _spec(MetricId.tool_calls_per_turn)
    empty = _turns(2, tool_calls=0)
    busy = _turns(2, tool_calls=1, zero_tool=False)
    tools = [tool(0), tool(1)]
    assert assess(spec, empty, [], empty, []).na_reason == "no_tools"
    assert assess(spec, busy, tools, empty, []).na_reason == "no_tools"
    stopped = assess(per_turn, empty, [], busy, tools)
    assert stopped.na_reason != "no_tools"
    assert stopped.applicable is True


def test_retry_coverage_boundary() -> None:
    spec = _spec(MetricId.tool_retry_rate)
    rows = _turns(1, tool_calls=100, zero_tool=False)
    low = [tool(0, has_args_hash=index < 89) for index in range(100)]
    enough = [tool(0, has_args_hash=index < 90) for index in range(100)]
    assert assess(spec, rows, low, rows, enough).na_reason == "coverage"
    assert assess(spec, rows, enough, rows, enough).applicable is True


def test_loop_coverage() -> None:
    spec = _spec(MetricId.loop_rate)
    low = [turn(index, loop_flag=False if index < 89 else None) for index in range(100)]
    enough = [turn(index, loop_flag=False if index < 90 else None) for index in range(100)]
    assert assess(spec, low, [], enough, []).na_reason == "coverage"
    assert assess(spec, enough, [], enough, []).applicable is True


def test_format_no_content_and_coverage() -> None:
    spec = _spec(MetricId.format_failure_rate)
    empty = _turns(4, format_ok=None)
    low = [turn(index, format_ok=True if index < 89 else None) for index in range(100)]
    enough = [turn(index, format_ok=True if index < 90 else None) for index in range(100)]
    assert assess(spec, empty, [], enough, []).na_reason == "no_content"
    assert assess(spec, low, [], enough, []).na_reason == "coverage"
    assert assess(spec, enough, [], enough, []).applicable is True


def test_output_unit_fallback() -> None:
    spec = _spec(MetricId.output_tokens_p50)
    tokens = _turns(20)
    chars = _turns(20, output_tokens=None)
    partial = [
        turn(index, output_tokens=None, output_chars=None if index < 2 else 10)
        for index in range(20)
    ]
    none = _turns(4, output_tokens=None, output_chars=None)
    assert assess(spec, tokens, [], tokens, []).unit.value == "tokens"
    assert assess(spec, chars, [], chars, []).unit.value == "chars"
    assert assess(spec, partial, [], chars, []).na_reason == "coverage"
    assert assess(spec, none, [], chars, []).na_reason == "no_content"


def test_cost_no_cost() -> None:
    spec = _spec(MetricId.cost_per_turn)
    low = [turn(index, cost_usd=0.01 if index < 89 else None) for index in range(100)]
    enough = [turn(index, cost_usd=0.01 if index < 90 else None) for index in range(100)]
    assert assess(spec, low, [], enough, []).na_reason == "no_cost"
    assert assess(spec, enough, [], enough, []).applicable is True


def test_sessions_minimum_and_inferred_share() -> None:
    spec = _spec(MetricId.turns_per_session)
    few = _turns(9)
    many = _turns(10)
    inferred = [turn(index, session_inferred=index < 6) for index in range(10)]
    assert assess(spec, few, [], many, []).na_reason == "no_sessions"
    assert assess(spec, inferred, [], many, []).na_reason == "no_sessions"
    assert assess(spec, many, [], many, []).applicable is True


def test_zero_denominator_for_empty_percentile() -> None:
    spec = _spec(MetricId.latency_p95)
    decision = assess(spec, [], [], [], [])
    assert decision.na_reason == "zero_denominator"
