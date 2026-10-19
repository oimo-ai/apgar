from __future__ import annotations

from datetime import timedelta
from typing import Any

from apgar.config import Settings
from apgar.domain.enums import Direction, VerdictState
from apgar.domain.models import Agent, Release, VerdictEvaluation
from apgar.domain.time import to_iso
from apgar.verdict.headline import detectability, failing_metrics, metric_headline
from apgar.verdict.numbers import finite
from apgar.verdict.power import delta_oriented


def _public_url(settings: Settings) -> str:
    return settings.public_url.rstrip("/")


def report_url(settings: Settings, agent_name: str, release: str) -> str:
    return f"{_public_url(settings)}/agents/{agent_name}/releases/{release}"


def _worst_slice(
    slices: dict[str, Any], metric: str, direction: Direction
) -> dict[str, str] | None:
    family = slices.get(metric)
    if not isinstance(family, dict):
        return None
    ranked: list[tuple[float, dict[str, str]]] = []
    for dimension, block in family.items():
        if not isinstance(block, dict):
            continue
        for value in block.get("values", []):
            if not isinstance(value, dict) or value.get("status") != "FAIL":
                continue
            delta = finite(value.get("delta"))
            if delta is None:
                continue
            choice = {"dimension": str(dimension), "value": str(value.get("value", ""))}
            ranked.append((delta_oriented(direction, delta), choice))
    if not ranked:
        return None
    tool_hits = [item for item in ranked if item[1]["dimension"] == "tool"]
    pool = tool_hits or ranked
    pool.sort(key=lambda item: item[0], reverse=True)
    return pool[0][1]


def pending_summary(agent: Agent, release: Release, settings: Settings) -> dict[str, Any]:
    max_end = to_iso(release.first_seen + timedelta(hours=agent.verdict_settings.max_window_hours))
    return {
        "agent": agent.name,
        "release": release.release,
        "verdict": release.state.value,
        "reason": release.reason.value,
        "final": release.final,
        "ok": None,
        "baseline": {"release": None, "mode": None, "unverified": False},
        "sample": {
            "candidate_turns": 0,
            "baseline_turns": 0,
            "candidate_sessions": 0,
            "baseline_sessions": 0,
        },
        "excluded": {"mixed": 0, "untagged": 0, "late": 0},
        "window": {"start": None, "end": None, "max_end": max_end},
        "evaluated_at": None,
        "early": False,
        "ended": None,
        "detectability": None,
        "failed_metrics": [],
        "report_url": report_url(settings, agent.name, release.release),
    }


def build_summary(
    agent: Agent,
    release: Release,
    evaluation: VerdictEvaluation,
    settings: Settings,
) -> dict[str, Any]:
    items = evaluation.metrics.get("items", {})
    failed: list[dict[str, Any]] = []
    for metric_id in failing_metrics(items):
        item = items[metric_id.value]
        try:
            direction = Direction(str(item.get("direction")))
        except ValueError:
            direction = Direction.up
        family = evaluation.slices.get(metric_id.value)
        failed.append(
            {
                "id": metric_id.value,
                "baseline": item.get("baseline"),
                "candidate": item.get("candidate"),
                "delta": item.get("delta"),
                "ci": item.get("ci"),
                "tolerance": item.get("tolerance"),
                "tolerance_mode": item.get("tolerance_mode"),
                "direction": item.get("direction"),
                "unit": item.get("unit"),
                "worst_slice": _worst_slice(evaluation.slices, metric_id.value, direction),
                "headline": metric_headline(metric_id, item, family, evaluation.n_candidate_turns),
            }
        )
    ended = evaluation.metrics.get("ended")
    state = release.state
    ok: bool | None
    if state is VerdictState.PASS:
        ok = True
    elif state is VerdictState.FAIL:
        ok = False
    else:
        ok = None
    max_end = to_iso(release.first_seen + timedelta(hours=agent.verdict_settings.max_window_hours))
    return {
        "agent": agent.name,
        "release": release.release,
        "verdict": state.value,
        "reason": release.reason.value,
        "final": release.final,
        "ok": ok,
        "baseline": {
            "release": release.selected_baseline_release or None,
            "mode": release.selected_baseline_mode or None,
            "unverified": release.baseline_unverified,
        },
        "sample": {
            "candidate_turns": evaluation.n_candidate_turns,
            "baseline_turns": evaluation.n_baseline_turns,
            "candidate_sessions": evaluation.n_candidate_sessions,
            "baseline_sessions": evaluation.n_baseline_sessions,
        },
        "excluded": {
            "mixed": evaluation.n_excluded_mixed,
            "untagged": evaluation.n_excluded_untagged,
            "late": evaluation.n_excluded_late,
        },
        "window": {
            "start": None if evaluation.window_start is None else to_iso(evaluation.window_start),
            "end": None if evaluation.window_end is None else to_iso(evaluation.window_end),
            "max_end": max_end,
        },
        "evaluated_at": to_iso(evaluation.evaluated_at),
        "early": bool(evaluation.metrics.get("early")),
        "ended": ended if isinstance(ended, dict) else None,
        "detectability": detectability(evaluation.metrics),
        "failed_metrics": failed,
        "report_url": report_url(settings, agent.name, release.release),
    }
