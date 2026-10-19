from __future__ import annotations

import math
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from apgar.domain.enums import (
    Direction,
    MetricId,
    MetricLevel,
    MetricRole,
    ToleranceMode,
)


class MetricSettings(BaseModel):
    enabled: bool = True
    direction: Direction
    tolerance_mode: ToleranceMode
    tolerance: float
    role: MetricRole

    @field_validator("tolerance")
    @classmethod
    def _tolerance_positive(cls, value: float) -> float:
        if math.isnan(value) or value <= 0:
            raise ValueError("tolerance must be greater than 0")
        return value


MIN_WINDOW_HOURS = 1
MAX_WINDOW_HOURS = 168
BASELINE_DAYS = 7
EARLY_MIN_TURNS = 20
# The cluster bootstrap resamples sessions; fewer than 5 gives too few distinct resamples.
EARLY_MIN_SESSIONS = 5


class VerdictSettings(BaseModel):
    min_turns: int = 200
    min_sessions: int = 30
    min_turns_slice: int = 100
    fail_confirmations: int = 2
    pass_confirmations: int = 2
    max_window_hours: int = Field(default=72, ge=MIN_WINDOW_HOURS, le=MAX_WINDOW_HOURS)
    include_mixed_sessions: bool = False
    alpha: float = 0.05
    confirmation_gap_minutes: int = 10
    notify_healthy: bool = True

    @classmethod
    def from_stored(cls, data: dict[str, Any]) -> VerdictSettings:
        hours = data.get("max_window_hours")
        if isinstance(hours, int):
            hours = min(max(hours, MIN_WINDOW_HOURS), MAX_WINDOW_HOURS)
            data = {**data, "max_window_hours": hours}
        return cls.model_validate(data)

    @property
    def early_floor(self) -> tuple[int, int]:
        return min(EARLY_MIN_TURNS, self.min_turns), min(EARLY_MIN_SESSIONS, self.min_sessions)


class ReleaseSettings(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    from_attribute: str | None = Field(default=None, alias="from")


class SurfaceMapping(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    from_attribute: str | None = Field(default=None, alias="from")


class AgentFilter(BaseModel):
    trace_name: str | None = None
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, str] = Field(default_factory=dict)
    environment: str | None = None


def _metric(
    direction: Direction,
    tolerance_mode: ToleranceMode,
    tolerance: float,
    role: MetricRole,
) -> MetricSettings:
    return MetricSettings(
        direction=direction,
        tolerance_mode=tolerance_mode,
        tolerance=tolerance,
        role=role,
    )


DEFAULT_METRICS: dict[MetricId, MetricSettings] = {
    MetricId.tool_error_rate: _metric(Direction.up, ToleranceMode.abs, 0.02, MetricRole.guardrail),
    MetricId.tool_retry_rate: _metric(Direction.up, ToleranceMode.abs, 0.02, MetricRole.guardrail),
    MetricId.loop_rate: _metric(Direction.up, ToleranceMode.abs, 0.01, MetricRole.guardrail),
    MetricId.tool_calls_per_turn: _metric(
        Direction.down, ToleranceMode.rel, 0.10, MetricRole.guardrail
    ),
    MetricId.zero_tool_turn_rate: _metric(
        Direction.up, ToleranceMode.abs, 0.05, MetricRole.guardrail
    ),
    MetricId.llm_error_rate: _metric(Direction.up, ToleranceMode.abs, 0.01, MetricRole.guardrail),
    MetricId.format_failure_rate: _metric(
        Direction.up, ToleranceMode.abs, 0.01, MetricRole.guardrail
    ),
    MetricId.output_tokens_p50: _metric(
        Direction.down, ToleranceMode.rel, 0.15, MetricRole.guardrail
    ),
    MetricId.latency_p95: _metric(Direction.up, ToleranceMode.rel, 0.15, MetricRole.guardrail),
    MetricId.cost_per_turn: _metric(Direction.up, ToleranceMode.rel, 0.20, MetricRole.guardrail),
    MetricId.turns_per_session: _metric(
        Direction.both, ToleranceMode.rel, 0.25, MetricRole.informational
    ),
}

METRIC_LEVELS: dict[MetricId, MetricLevel] = {
    MetricId.tool_error_rate: MetricLevel.tool,
    MetricId.tool_retry_rate: MetricLevel.tool,
    MetricId.loop_rate: MetricLevel.turn,
    MetricId.tool_calls_per_turn: MetricLevel.turn,
    MetricId.zero_tool_turn_rate: MetricLevel.turn,
    MetricId.llm_error_rate: MetricLevel.turn,
    MetricId.format_failure_rate: MetricLevel.turn,
    MetricId.output_tokens_p50: MetricLevel.turn,
    MetricId.latency_p95: MetricLevel.turn,
    MetricId.cost_per_turn: MetricLevel.turn,
    MetricId.turns_per_session: MetricLevel.session,
}


METRIC_GROUPS: dict[str, tuple[MetricId, ...]] = {
    "behavior": (
        MetricId.tool_calls_per_turn,
        MetricId.zero_tool_turn_rate,
        MetricId.tool_retry_rate,
        MetricId.loop_rate,
        MetricId.output_tokens_p50,
        MetricId.format_failure_rate,
        MetricId.turns_per_session,
    ),
    "reliability": (MetricId.tool_error_rate, MetricId.llm_error_rate),
    "cost_latency": (MetricId.cost_per_turn, MetricId.latency_p95),
}
METRIC_ORDER: tuple[MetricId, ...] = tuple(
    metric for group in METRIC_GROUPS.values() for metric in group
)


def metric_group(metric: MetricId) -> str:
    return next(name for name, members in METRIC_GROUPS.items() if metric in members)


def effective_metric_settings(
    overrides: dict[str, dict[str, Any]],
) -> dict[MetricId, MetricSettings]:
    merged: dict[MetricId, MetricSettings] = {}
    for metric_id, base in DEFAULT_METRICS.items():
        data = base.model_dump()
        data.update(overrides.get(metric_id.value, {}))
        merged[metric_id] = MetricSettings.model_validate(data)
    return merged
