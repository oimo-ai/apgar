from __future__ import annotations

from typing import Any

from apgar.domain.enums import (
    Direction,
    MetricId,
    MetricStatus,
    MetricUnit,
    SliceStatus,
    ToleranceMode,
)
from apgar.domain.settings import METRIC_GROUPS
from apgar.verdict.numbers import finite

MINUS = "\u2212"

METRIC_LABELS: dict[MetricId, str] = {
    MetricId.tool_error_rate: "Tool error rate",
    MetricId.tool_retry_rate: "Retry rate",
    MetricId.loop_rate: "Loop rate",
    MetricId.tool_calls_per_turn: "Tool calls per turn",
    MetricId.zero_tool_turn_rate: "Turns without tools",
    MetricId.llm_error_rate: "LLM error rate",
    MetricId.format_failure_rate: "Format failure rate",
    MetricId.output_tokens_p50: "Output length",
    MetricId.latency_p95: "Latency p95",
    MetricId.cost_per_turn: "Cost per turn",
    MetricId.turns_per_session: "Turns per session",
}
_DIMENSIONS = ("tool", "surface", "session_depth", "response_model", "prompt_version")
_DIMENSION_LABELS = {
    "tool": "tools",
    "surface": "surfaces",
    "session_depth": "session depth",
    "response_model": "models",
    "prompt_version": "prompt versions",
}
_DIMENSION_PREFIX = {
    "tool": "",
    "surface": "surface ",
    "session_depth": "depth ",
    "response_model": "model ",
    "prompt_version": "prompt ",
}


def _sign(value: float) -> str:
    if value > 0:
        return "+"
    if value < 0:
        return MINUS
    return ""


def _points(tolerance: float) -> str:
    scaled = tolerance * 100
    if abs(scaled - round(scaled)) < 1e-6:
        return str(round(scaled))
    return f"{scaled:.1f}"


def format_rate(value: float) -> str:
    pct = value * 100
    digits = 2 if pct != 0 and abs(pct) < 1 else 1
    body = f"{abs(pct):.{digits}f}"
    return f"{MINUS if pct < 0 else ''}{body}%"


def format_pp(delta: float) -> str:
    pct = delta * 100
    return f"{_sign(pct)}{abs(pct):.1f} pp"


def format_rel(delta: float) -> str:
    pct = delta * 100
    return f"{_sign(pct)}{abs(pct):.0f}%"


def format_count(value: float) -> str:
    return f"{round(value):,}"


def format_value(value: object, unit: str) -> str:
    number = finite(value)
    if number is None:
        return "n/a"
    if unit == MetricUnit.rate.value:
        return format_rate(number)
    if unit == MetricUnit.count_.value:
        return f"{number:.2f}"
    if unit == MetricUnit.usd.value:
        return f"${number:.4f}"
    if unit in {MetricUnit.ms.value, MetricUnit.tokens.value, MetricUnit.chars.value}:
        return f"{format_count(number)} {unit}"
    return format_count(number)


def format_change(value: object, mode: str) -> str:
    number = finite(value)
    if number is None:
        return "n/a"
    return format_rel(number) if mode == ToleranceMode.rel.value else format_pp(number)


def allowed(mode: str, direction: str, tolerance: float) -> str:
    unit = " pp" if mode == ToleranceMode.abs.value else "%"
    number = _points(tolerance)
    if direction == Direction.both.value:
        return f"±{number}{unit}"
    if direction == Direction.down.value:
        return f"down to {MINUS}{number}{unit}"
    return f"up to +{number}{unit}"


def _join(values: list[str]) -> str:
    if len(values) <= 2:
        return " and ".join(values)
    return ", ".join(values[:-1]) + f", and {values[-1]}"


def attribution(family: object, n_turns: int) -> str:
    concentrated: list[str] = []
    uniform: list[str] = []
    sufficient = False
    blocks = family if isinstance(family, dict) else {}
    for dimension in _DIMENSIONS:
        block = blocks.get(dimension)
        values = block.get("values", []) if isinstance(block, dict) else []
        rows = [row for row in values if isinstance(row, dict)]
        failing = [str(row.get("value", "")) for row in rows if row.get("status") == "FAIL"]
        clean = [row for row in rows if row.get("status") == SliceStatus.NOT_FLAGGED.value]
        sufficient = sufficient or bool(failing or clean)
        if failing and clean:
            concentrated.append(_DIMENSION_PREFIX[dimension] + _join(failing))
        elif failing:
            uniform.append(_DIMENSION_LABELS[dimension])
    parts: list[str] = []
    if concentrated:
        parts.append(f"Concentrated in {', '.join(concentrated)}")
    if uniform:
        parts.append(f"{'u' if parts else 'U'}niform across {_join(uniform)}")
    if not parts and sufficient:
        return "No single slice stands out."
    if not parts:
        return f"Attribution pending ({format_count(n_turns)} turns)."
    return "; ".join(parts) + "."


def metric_headline(metric_id: MetricId, item: dict[str, Any], family: object, n_turns: int) -> str:
    mode = str(item.get("tolerance_mode") or ToleranceMode.abs.value)
    direction = str(item.get("direction") or Direction.up.value)
    unit = str(item.get("unit") or MetricUnit.rate.value)
    delta = finite(item.get("delta")) or 0.0
    verb = "rose" if delta > 0 else "fell" if delta < 0 else "changed"
    tolerance = finite(item.get("tolerance")) or 0.0
    first = (
        f"{METRIC_LABELS[metric_id]} {verb} from {format_value(item.get('baseline'), unit)} "
        f"to {format_value(item.get('candidate'), unit)} "
        f"(allowed: {allowed(mode, direction, tolerance)})."
    )
    return f"{first} {attribution(family, n_turns)}"


def _distance(item: dict[str, Any]) -> float:
    ci = item.get("ci")
    tolerance = finite(item.get("tolerance")) or 0.0
    if not isinstance(ci, list) or len(ci) != 2:
        return 0.0
    lower, upper = finite(ci[0]), finite(ci[1])
    if lower is None or upper is None or upper <= lower:
        return 0.0
    direction = item.get("direction")
    if direction == Direction.down.value:
        bound = -upper
    elif direction == Direction.both.value:
        bound = max(lower, -upper)
    else:
        bound = lower
    return (bound - tolerance) / ((upper - lower) / 2)


def failing_metrics(items: object) -> list[MetricId]:
    if not isinstance(items, dict):
        return []
    failing: list[tuple[int, float, MetricId]] = []
    for rank, group in enumerate(METRIC_GROUPS.values()):
        for metric_id in group:
            item = items.get(metric_id.value)
            if not isinstance(item, dict):
                continue
            if item.get("role") == "guardrail" and item.get("status") == MetricStatus.FAIL.value:
                failing.append((rank, -_distance(item), metric_id))
    return [metric_id for _rank, _distance_key, metric_id in sorted(failing)]


def detectability(metrics: dict[str, Any]) -> str | None:
    headline = metrics.get("headline_metric")
    items = metrics.get("items")
    if not isinstance(headline, str) or not isinstance(items, dict):
        return None
    item = items.get(headline)
    if not isinstance(item, dict) or headline not in MetricId._value2member_map_:
        return None
    value = finite(item.get("detectable_degradation"))
    if value is None:
        return None
    change = format_change(value, str(item.get("tolerance_mode") or ToleranceMode.abs.value))
    label = METRIC_LABELS[MetricId(headline)].lower()
    return f"Can currently detect a change of {change} or more in {label}."
