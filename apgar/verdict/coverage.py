from __future__ import annotations

from typing import Any

from apgar.domain.enums import MetricId, OutputFormat
from apgar.domain.models import Agent
from apgar.domain.settings import METRIC_GROUPS
from apgar.verdict.numbers import finite

_ARGUMENT_METRICS = {MetricId.tool_retry_rate, MetricId.loop_rate}
_MISSING = {
    "no_tools": "tool spans",
    "no_content": "message content",
    "no_sessions": "session id",
    "no_cost": "cost on chat spans",
    "disabled": "disabled in settings",
    "zero_denominator": "no qualifying traffic",
}
LOW_BEHAVIOR_COVERAGE = 0.5


def missing_input(metric_id: MetricId, na_reason: str) -> str:
    if na_reason == "coverage":
        return "tool arguments" if metric_id in _ARGUMENT_METRICS else "message content"
    return _MISSING.get(na_reason, na_reason)


def _share(item: dict[str, Any]) -> float | None:
    coverage = item.get("coverage")
    if not isinstance(coverage, dict):
        return None
    shares = [finite(coverage.get(arm)) for arm in ("candidate", "baseline")]
    known = [share for share in shares if share is not None]
    return min(known) if known else None


def metric_coverage(agent: Agent, items: object) -> dict[str, Any] | None:
    if not isinstance(items, dict) or not items:
        return None
    metrics: list[dict[str, Any]] = []
    groups: dict[str, dict[str, int]] = {}
    for group, metric_ids in METRIC_GROUPS.items():
        counts = {"active": 0, "total": 0}
        for metric_id in metric_ids:
            if (
                metric_id is MetricId.format_failure_rate
                and agent.output_format is not OutputFormat.json
            ):
                continue
            item = items.get(metric_id.value)
            if not isinstance(item, dict):
                continue
            active = item.get("applicable") is not False
            reason = str(item.get("na_reason") or "")
            counts["total"] += 1
            counts["active"] += int(active)
            metrics.append(
                {
                    "id": metric_id.value,
                    "group": group,
                    "active": active,
                    "missing": None if active else missing_input(metric_id, reason),
                    "share": _share(item),
                }
            )
        groups[group] = counts
    return {
        "active": sum(group["active"] for group in groups.values()),
        "total": sum(group["total"] for group in groups.values()),
        "groups": groups,
        "metrics": metrics,
    }


def behavior_low(coverage: dict[str, Any] | None) -> bool:
    if coverage is None:
        return False
    behavior = coverage["groups"].get("behavior", {"active": 0, "total": 0})
    active, total = int(behavior["active"]), int(behavior["total"])
    return total > 0 and active / total < LOW_BEHAVIOR_COVERAGE
