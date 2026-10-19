from __future__ import annotations

import math

import pytest
from pydantic import ValidationError

from apgar.domain.canonical import canonical_json
from apgar.domain.enums import (
    Direction,
    MetricId,
    MetricLevel,
    MetricRole,
    NotificationEvent,
    ReasonCode,
    ToleranceMode,
)
from apgar.domain.naming import slugify
from apgar.domain.settings import (
    DEFAULT_METRICS,
    METRIC_LEVELS,
    MetricSettings,
    VerdictSettings,
    effective_metric_settings,
)

_METRIC_ORDER = [
    "tool_error_rate",
    "tool_retry_rate",
    "loop_rate",
    "tool_calls_per_turn",
    "zero_tool_turn_rate",
    "llm_error_rate",
    "format_failure_rate",
    "output_tokens_p50",
    "latency_p95",
    "cost_per_turn",
    "turns_per_session",
]

_DEFAULT_TABLE = [
    (
        "tool_error_rate",
        MetricLevel.tool,
        Direction.up,
        ToleranceMode.abs,
        0.02,
        MetricRole.guardrail,
    ),
    (
        "tool_retry_rate",
        MetricLevel.tool,
        Direction.up,
        ToleranceMode.abs,
        0.02,
        MetricRole.guardrail,
    ),
    ("loop_rate", MetricLevel.turn, Direction.up, ToleranceMode.abs, 0.01, MetricRole.guardrail),
    (
        "tool_calls_per_turn",
        MetricLevel.turn,
        Direction.down,
        ToleranceMode.rel,
        0.10,
        MetricRole.guardrail,
    ),
    (
        "zero_tool_turn_rate",
        MetricLevel.turn,
        Direction.up,
        ToleranceMode.abs,
        0.05,
        MetricRole.guardrail,
    ),
    (
        "llm_error_rate",
        MetricLevel.turn,
        Direction.up,
        ToleranceMode.abs,
        0.01,
        MetricRole.guardrail,
    ),
    (
        "format_failure_rate",
        MetricLevel.turn,
        Direction.up,
        ToleranceMode.abs,
        0.01,
        MetricRole.guardrail,
    ),
    (
        "output_tokens_p50",
        MetricLevel.turn,
        Direction.down,
        ToleranceMode.rel,
        0.15,
        MetricRole.guardrail,
    ),
    ("latency_p95", MetricLevel.turn, Direction.up, ToleranceMode.rel, 0.15, MetricRole.guardrail),
    (
        "cost_per_turn",
        MetricLevel.turn,
        Direction.up,
        ToleranceMode.rel,
        0.20,
        MetricRole.guardrail,
    ),
    (
        "turns_per_session",
        MetricLevel.session,
        Direction.both,
        ToleranceMode.rel,
        0.25,
        MetricRole.informational,
    ),
]


def test_metric_ids_in_appendix_b_order() -> None:
    assert [item.value for item in MetricId] == _METRIC_ORDER


def test_default_metric_settings_table() -> None:
    assert list(DEFAULT_METRICS) == list(MetricId)
    for metric_id, level, direction, mode, tolerance, role in _DEFAULT_TABLE:
        parsed = MetricId(metric_id)
        settings = DEFAULT_METRICS[parsed]
        assert METRIC_LEVELS[parsed] == level
        assert settings.enabled is True
        assert settings.direction == direction
        assert settings.tolerance_mode == mode
        assert settings.tolerance == tolerance
        assert settings.role == role


def test_verdict_defaults() -> None:
    settings = VerdictSettings()
    assert settings.min_turns == 200
    assert settings.min_sessions == 30
    assert settings.min_turns_slice == 100
    assert settings.fail_confirmations == 2
    assert settings.pass_confirmations == 2
    assert settings.max_window_hours == 72
    assert settings.include_mixed_sessions is False
    assert settings.alpha == 0.05
    assert settings.confirmation_gap_minutes == 10
    assert settings.early_floor == (20, 5)


def test_early_floor_caps_at_minimum() -> None:
    assert VerdictSettings(min_turns=10, min_sessions=3).early_floor == (10, 3)


def test_effective_metric_settings_merges_overrides() -> None:
    merged = effective_metric_settings({"tool_error_rate": {"tolerance": 0.05, "enabled": False}})
    updated = merged[MetricId.tool_error_rate]
    assert updated.tolerance == 0.05
    assert updated.enabled is False
    assert updated.direction == Direction.up
    assert updated.role == MetricRole.guardrail
    assert merged[MetricId.llm_error_rate] == DEFAULT_METRICS[MetricId.llm_error_rate]


def test_tolerance_rejects_non_positive_values() -> None:
    with pytest.raises(ValidationError):
        MetricSettings(
            direction=Direction.up,
            tolerance_mode=ToleranceMode.abs,
            tolerance=math.nan,
            role=MetricRole.guardrail,
        )


def test_removed_reason_and_event_names_are_rejected() -> None:
    for reason in ("soak_expired", "session_affinity"):
        with pytest.raises(ValueError):
            ReasonCode(reason)
    for event in ("first_inconclusive", "fail", "pass", "soak_expired", "manual"):
        with pytest.raises(ValueError):
            NotificationEvent(event)


def test_slugify_rules() -> None:
    assert slugify("Billing Copilot") == "billing-copilot"
    assert slugify("foo..bar") == "foo..bar"
    assert slugify("---") == "agent"
    assert slugify(".Release.") == "release"
    assert slugify("_bot") == "bot"
    assert slugify("_.-bot") == "bot"
    assert slugify("___") == "agent"
    assert slugify("bot_") == "bot_"


def test_canonical_json_sorts_keys() -> None:
    assert canonical_json({"b": 1, "a": "x"}) == b'{"a":"x","b":1}'
