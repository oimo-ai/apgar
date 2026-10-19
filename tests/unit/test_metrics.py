from __future__ import annotations

from datetime import UTC, datetime, timedelta

from apgar.domain.enums import MetricId, MetricUnit, OutputFormat
from apgar.storage.types import ArmData, ArmToolCall, ArmTurn
from apgar.verdict.metrics import (
    agent_metric_settings,
    default_specs,
    point_quantile,
    point_ratio,
    specs_for,
    unit_arrays,
)
from tests.factories import make_agent

NOW = datetime(2026, 10, 8, 9, 0, tzinfo=UTC)


def test_format_metric_only_for_json_agents() -> None:
    text = specs_for(agent_metric_settings(make_agent(NOW, output_format=OutputFormat.text)))
    json = specs_for(agent_metric_settings(make_agent(NOW, output_format=OutputFormat.json)))
    assert MetricId.format_failure_rate not in {spec.id for spec in text}
    assert len(text) == len(MetricId) - 1
    assert {spec.id for spec in json} == set(MetricId)


def turn(index: int, **overrides: object) -> ArmTurn:
    start = NOW + timedelta(minutes=index)
    row = ArmTurn(
        turn_id=f"t{index}",
        trace_id=f"{index:032x}",
        session_id="s0",
        start_ts=start,
        end_ts=start,
        surface="web",
        depth_bucket="short",
        response_model="gpt-4.1",
        prompt_version="v1",
        turn_index=index,
        mixed_session=False,
        session_inferred=False,
        session_closed=True,
        llm_error=False,
        tool_calls=0,
        tool_errors=0,
        zero_tool=True,
        loop_flag=False,
        format_ok=True,
        output_tokens=10 * (index + 1),
        output_chars=40 * (index + 1),
        latency_ms=100 * (index + 1),
        cost_usd=0.01 * (index + 1),
        tools_called=[],
    )
    for key, value in overrides.items():
        setattr(row, key, value)
    return row


def tool(index: int, name: str = "sql_query", **overrides: object) -> ArmToolCall:
    row = ArmToolCall(
        turn_id=f"t{index}",
        session_id="s0",
        tool_name=name,
        is_error=False,
        has_args_hash=True,
        is_retry=False,
        surface="web",
        depth_bucket="short",
        response_model="gpt-4.1",
        prompt_version="v1",
    )
    for key, value in overrides.items():
        setattr(row, key, value)
    return row


def arm(turns: list[ArmTurn], tools: list[ArmToolCall]) -> ArmData:
    return ArmData(turns, tools, 0, 0, 0)


def _hand() -> tuple[list[ArmTurn], list[ArmToolCall]]:
    common = {"tool_calls": 0, "zero_tool": True}
    turns = [
        turn(0, session_id="s0", tool_calls=2, tool_errors=1, zero_tool=False, tools_called=["a"]),
        turn(1, session_id="s0", tool_calls=1, zero_tool=False, tools_called=["sql"]),
        turn(2, session_id="s0", loop_flag=True),
        turn(
            3,
            session_id="s0",
            loop_flag=None,
            llm_error=True,
            format_ok=None,
            cost_usd=None,
        ),
        turn(4, session_id="s1", tool_calls=2, zero_tool=False, tools_called=["mail"]),
        turn(5, session_id="s1", tool_calls=1, tool_errors=1, zero_tool=False, tools_called=["b"]),
        turn(6, session_id="s1", **common),
        turn(7, session_id="s1", format_ok=False),
        turn(
            8,
            session_id="s2",
            tool_calls=2,
            tool_errors=1,
            zero_tool=False,
            session_closed=False,
            tools_called=["sql"],
        ),
        turn(
            9,
            session_id="s2",
            tool_calls=1,
            zero_tool=False,
            session_closed=False,
            tools_called=["sql"],
        ),
        turn(10, session_id="s2", session_closed=False),
        turn(11, session_id="s2", session_closed=False, cost_usd=None),
    ]
    tools = [
        tool(0, "sql", is_error=True, session_id="s0"),
        tool(0, "sql", session_id="s0", is_retry=True),
        tool(1, "sql", session_id="s0"),
        tool(4, "mail", session_id="s1"),
        tool(4, "mail", session_id="s1", has_args_hash=False),
        tool(5, "mail", is_error=True, session_id="s1"),
        tool(8, "sql", is_error=True, session_id="s2"),
        tool(8, "sql", session_id="s2"),
        tool(9, "sql", session_id="s2"),
    ]
    return turns, tools


def test_unit_arrays_match_hand_values() -> None:
    turns, tools = _hand()
    data = arm(turns, tools)
    specs = {spec.id: spec for spec in default_specs()}
    arrays = {metric: unit_arrays(specs[metric], data, specs[metric].unit) for metric in MetricId}

    def ratio(metric: MetricId) -> float:
        item = arrays[metric]
        return point_ratio(item.num, item.den)

    assert ratio(MetricId.tool_error_rate) == 3 / 9
    assert ratio(MetricId.tool_retry_rate) == 1 / 8
    assert ratio(MetricId.loop_rate) == 1 / 11
    assert ratio(MetricId.tool_calls_per_turn) == 9 / 12
    assert ratio(MetricId.zero_tool_turn_rate) == 6 / 12
    assert ratio(MetricId.llm_error_rate) == 1 / 12
    assert ratio(MetricId.format_failure_rate) == 1 / 11
    costs = [item.cost_usd for item in turns if item.cost_usd is not None]
    assert ratio(MetricId.cost_per_turn) == sum(costs) / len(costs)
    assert ratio(MetricId.turns_per_session) == 4
    tokens = [float(item.output_tokens) for item in turns if item.output_tokens is not None]
    observed = point_quantile(arrays[MetricId.output_tokens_p50].values, 0.5)
    assert observed in set(tokens)
    latency = point_quantile(arrays[MetricId.latency_p95].values, 0.95)
    assert latency in {float(item.latency_ms) for item in turns}


def test_output_unit_switches_to_chars() -> None:
    turns, tools = _hand()
    data = arm(turns, tools)
    spec = next(item for item in default_specs() if item.id is MetricId.output_tokens_p50)
    chars = unit_arrays(spec, data, MetricUnit.chars)
    assert chars.values.size == 12
    assert float(chars.values[0]) == 40
