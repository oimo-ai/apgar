from __future__ import annotations

from typing import Any

import pytest

from apgar.domain.enums import MetricId
from apgar.verdict.headline import (
    MINUS,
    allowed,
    attribution,
    detectability,
    failing_metrics,
    format_value,
    metric_headline,
)


def _block(*rows: tuple[str, str]) -> dict[str, Any]:
    return {"values": [{"value": value, "status": status} for value, status in rows]}


def test_attribution_concentrated_uniform_and_pending() -> None:
    family = {
        "tool": _block(("web_search", "FAIL"), ("fetch_url", "FAIL"), ("sql", "NOT_FLAGGED")),
        "response_model": _block(("gpt-a", "FAIL"), ("gpt-b", "FAIL")),
        "session_depth": _block(("long", "FAIL"), ("short", "FAIL"), ("mid", "INSUFFICIENT")),
        "surface": _block(("web", "INSUFFICIENT")),
    }
    assert attribution(family, 400) == (
        "Concentrated in web_search and fetch_url; uniform across session depth and models."
    )
    assert attribution({"prompt_version": _block(("p1", "FAIL"))}, 90) == (
        "Uniform across prompt versions."
    )
    three = {"surface": _block(("a", "FAIL"), ("b", "FAIL"), ("c", "FAIL"), ("d", "NOT_FLAGGED"))}
    assert attribution(three, 90) == "Concentrated in surface a, b, and c."
    assert attribution({}, 38) == "Attribution pending (38 turns)."
    assert attribution(None, 38) == "Attribution pending (38 turns)."


def test_metric_headline_and_allowed() -> None:
    item = {
        "baseline": 0.026,
        "candidate": 0.271,
        "delta": 0.245,
        "tolerance": 0.02,
        "tolerance_mode": "abs",
        "direction": "up",
        "unit": "rate",
    }
    family = {"tool": _block(("web_search", "FAIL"), ("sql", "NOT_FLAGGED"))}
    assert metric_headline(MetricId.tool_error_rate, item, family, 80) == (
        "Tool error rate rose from 2.6% to 27.1% (allowed: up to +2 pp). "
        "Concentrated in web_search."
    )
    down = {**item, "delta": -0.3, "unit": "tokens", "baseline": 412, "candidate": 288}
    assert metric_headline(MetricId.output_tokens_p50, down, None, 50).startswith(
        "Output length fell from 412 tokens to 288 tokens"
    )
    assert allowed("rel", "down", 0.1) == f"down to {MINUS}10%"
    assert allowed("rel", "both", 0.25) == "±25%"
    assert allowed("abs", "up", 0.015) == "up to +1.5 pp"


@pytest.mark.parametrize(
    ("value", "unit", "text"),
    [
        (None, "rate", "n/a"),
        (float("nan"), "rate", "n/a"),
        (0.004, "rate", "0.40%"),
        (1.5, "count", "1.50"),
        (0.0123, "usd", "$0.0123"),
        (1234.4, "ms", "1,234 ms"),
        (7, "other", "7"),
    ],
)
def test_format_value(value: object, unit: str, text: str) -> None:
    assert format_value(value, unit) == text


def _fail(lo: float, hi: float, role: str = "guardrail", direction: str = "up") -> dict[str, Any]:
    return {
        "role": role,
        "status": "FAIL",
        "ci": [lo, hi],
        "tolerance": 0.02,
        "direction": direction,
    }


def test_failing_metrics_ordered_by_group_then_distance() -> None:
    items = {
        "cost_per_turn": _fail(0.5, 0.9),
        "tool_error_rate": _fail(0.03, 0.05),
        "llm_error_rate": _fail(0.20, 0.22),
        "loop_rate": _fail(0.03, 0.2),
        "output_tokens_p50": _fail(-0.5, -0.3, direction="down"),
        "turns_per_session": _fail(0.5, 0.9, role="informational"),
        "format_failure_rate": {"role": "guardrail", "status": "PASS"},
        "tool_retry_rate": {**_fail(0.1, 0.2), "ci": None},
        "zero_tool_turn_rate": _fail(0.1, 0.4, direction="both"),
    }
    assert failing_metrics(items) == [
        MetricId.output_tokens_p50,
        MetricId.zero_tool_turn_rate,
        MetricId.loop_rate,
        MetricId.tool_retry_rate,
        MetricId.llm_error_rate,
        MetricId.tool_error_rate,
        MetricId.cost_per_turn,
    ]
    assert failing_metrics(None) == []


def test_detectability_line() -> None:
    metrics = {
        "headline_metric": "tool_error_rate",
        "items": {"tool_error_rate": {"detectable_degradation": 0.041, "tolerance_mode": "abs"}},
    }
    assert detectability(metrics) == (
        "Can currently detect a change of +4.1 pp or more in tool error rate."
    )
    assert detectability({"headline_metric": "nope", "items": {}}) is None
    assert detectability({"headline_metric": None}) is None
    blank = {"headline_metric": "tool_error_rate", "items": {"tool_error_rate": {}}}
    assert detectability(blank) is None
