from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from apgar.domain.enums import MetricId, OutputFormat
from apgar.domain.settings import METRIC_ORDER
from apgar.verdict.coverage import behavior_low, metric_coverage, missing_input
from tests.factories import make_agent

NOW = datetime(2026, 10, 8, 9, 30, tzinfo=UTC)


def _items(**na: str) -> dict[str, Any]:
    items: dict[str, Any] = {}
    for metric_id in METRIC_ORDER:
        reason = na.get(metric_id.value)
        items[metric_id.value] = {
            "applicable": reason is None,
            "na_reason": reason,
            "coverage": {"candidate": 0.4, "baseline": 0.95} if reason == "coverage" else None,
        }
    return items


def test_metric_coverage_counts_and_missing_inputs() -> None:
    agent = make_agent(NOW, output_format=OutputFormat.json)
    items = _items(
        tool_retry_rate="coverage",
        loop_rate="coverage",
        format_failure_rate="no_content",
        cost_per_turn="no_cost",
        latency_p95="disabled",
    )
    coverage = metric_coverage(agent, items)
    assert coverage is not None
    assert (coverage["active"], coverage["total"]) == (6, 11)
    assert coverage["groups"]["behavior"] == {"active": 4, "total": 7}
    missing = {
        row["id"]: (row["missing"], row["reason"])
        for row in coverage["metrics"]
        if not row["active"]
    }
    assert missing == {
        "tool_retry_rate": ("tool arguments", "coverage"),
        "loop_rate": ("tool arguments", "coverage"),
        "format_failure_rate": ("message content", "no_content"),
        "cost_per_turn": ("cost on chat spans", "no_cost"),
        "latency_p95": (None, "disabled"),
    }
    retry = next(row for row in coverage["metrics"] if row["id"] == "tool_retry_rate")
    assert retry["share"] == 0.4
    active = next(row for row in coverage["metrics"] if row["id"] == "tool_error_rate")
    assert (active["missing"], active["reason"]) == (None, None)
    assert behavior_low(coverage) is False


def test_text_agent_excludes_format_metric() -> None:
    agent = make_agent(NOW, output_format=OutputFormat.text)
    items = _items(
        tool_retry_rate="coverage",
        loop_rate="coverage",
        format_failure_rate="no_content",
    )
    coverage = metric_coverage(agent, items)
    assert coverage is not None
    assert (coverage["active"], coverage["total"]) == (8, 10)
    assert coverage["groups"]["behavior"] == {"active": 4, "total": 6}
    assert "format_failure_rate" not in {row["id"] for row in coverage["metrics"]}


def test_behavior_warning_below_half_and_unknown_coverage() -> None:
    agent = make_agent(NOW, output_format=OutputFormat.json)
    items = _items(
        tool_retry_rate="coverage",
        loop_rate="coverage",
        format_failure_rate="no_content",
        output_tokens_p50="coverage",
    )
    coverage = metric_coverage(agent, items)
    assert coverage is not None
    assert coverage["groups"]["behavior"] == {"active": 3, "total": 7}
    assert behavior_low(coverage) is True
    assert metric_coverage(agent, {}) is None
    assert metric_coverage(agent, None) is None
    assert behavior_low(None) is False


def test_missing_input_mapping() -> None:
    assert missing_input(MetricId.format_failure_rate, "no_content") == "message content"
    assert missing_input(MetricId.format_failure_rate, "coverage") == "message content"
    output = missing_input(MetricId.output_tokens_p50, "coverage")
    assert output == "token counts or message content"
    assert missing_input(MetricId.loop_rate, "coverage") == "tool arguments"
    assert missing_input(MetricId.turns_per_session, "no_sessions") == "session id"
    assert missing_input(MetricId.tool_error_rate, "no_tools") is None
    assert missing_input(MetricId.cost_per_turn, "disabled") is None
    assert missing_input(MetricId.latency_p95, "zero_denominator") is None
