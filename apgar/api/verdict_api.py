from __future__ import annotations

from datetime import timedelta
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ValidationError

from apgar.api.errors import ApiError, validation_message
from apgar.api.present import release_out
from apgar.domain.enums import (
    JobRequestKind,
    VerdictState,
)
from apgar.domain.models import (
    Agent,
    JobRequest,
    Release,
    ReleaseEvent,
    VerdictEvaluation,
)
from apgar.domain.retention import (
    RETENTION_DEFAULTS,
    TRACE_DATA_DAYS,
    TRACE_EXPIRED,
    trace_window_stored,
)
from apgar.domain.time import to_iso
from apgar.verdict.coverage import metric_coverage
from apgar.verdict.state_machine import fold_events
from apgar.verdict.summary import pending_summary
from apgar.worker.jobs.verdict import next_check_due


async def parse_body(request: Any, model: type[BaseModel]) -> Any:
    try:
        payload = await request.json()
    except Exception as exc:
        raise ApiError("validation_error", 422, "validation failed") from exc
    try:
        return model.model_validate(payload)
    except ValidationError as exc:
        raise ApiError(
            "validation_error",
            422,
            validation_message(list(exc.errors())),  # type: ignore[arg-type]
        ) from exc


def evaluation_out(evaluation: VerdictEvaluation, include_slices: bool) -> dict[str, Any]:
    body: dict[str, Any] = {
        "evaluated_at": to_iso(evaluation.evaluated_at),
        "manual": evaluation.manual,
        "seed": evaluation.seed,
        "baseline_release": evaluation.baseline_release or None,
        "baseline_mode": evaluation.baseline_mode or None,
        "baseline_unverified": evaluation.baseline_unverified,
        "window_start": None
        if evaluation.window_start is None
        else to_iso(evaluation.window_start),
        "window_end": None if evaluation.window_end is None else to_iso(evaluation.window_end),
        "n_candidate_turns": evaluation.n_candidate_turns,
        "n_baseline_turns": evaluation.n_baseline_turns,
        "n_candidate_sessions": evaluation.n_candidate_sessions,
        "n_baseline_sessions": evaluation.n_baseline_sessions,
        "n_excluded_mixed": evaluation.n_excluded_mixed,
        "n_excluded_untagged": evaluation.n_excluded_untagged,
        "n_excluded_late": evaluation.n_excluded_late,
        "state": evaluation.state.value,
        "reason": evaluation.reason.value,
        "final": evaluation.final,
        "metrics": evaluation.metrics,
        "duration_ms": evaluation.duration_ms,
    }
    if include_slices:
        body["slices"] = evaluation.slices
    return body


def event_out(event: ReleaseEvent) -> dict[str, Any]:
    return {
        "ts": to_iso(event.ts),
        "type": event.type.value,
        "payload": event.payload,
        "actor": event.actor or None,
    }


async def enqueue(
    request: Any, agent_id: str, release: str, kind: JobRequestKind, payload: dict[str, Any]
) -> None:
    now = request.app.state.clock()
    await request.app.state.meta_store.enqueue_job(
        JobRequest(
            id=str(uuid4()),
            agent_id=agent_id,
            release=release,
            kind=kind,
            payload=payload,
            requested_at=now,
            processed_at=None,
            updated_at=now,
        )
    )


async def stored_trace_days(meta: Any) -> int:
    raw = await meta.get_setting(f"retention.{TRACE_DATA_DAYS}")
    return RETENTION_DEFAULTS[TRACE_DATA_DAYS] if raw is None else int(raw)


async def require_trace_window(request: Any, release: Release) -> None:
    days = await stored_trace_days(request.app.state.meta_store)
    if not trace_window_stored(release.first_seen, request.app.state.clock(), days):
        raise ApiError("not_allowed", 400, TRACE_EXPIRED)


async def release_or_404(request: Any, agent: Agent, release: str) -> Release:
    found: Release | None = await request.app.state.meta_store.get_release(agent.id, release)
    if found is None:
        raise ApiError("not_found", 404, "release not found")
    return found


async def release_detail(request: Any, agent: Agent, release: Release) -> dict[str, Any]:
    meta = request.app.state.meta_store
    now = request.app.state.clock()
    events = await meta.release_events(agent.id, release.release)
    user_state = fold_events(events)
    evaluations = await meta.list_evaluations(agent.id, release.release, limit=1)
    latest = evaluations[0] if evaluations else None
    settings = request.app.state.settings
    hours = agent.verdict_settings.max_window_hours
    next_check = None
    if not release.final and not agent.is_demo:
        next_check = next_check_due(
            release.last_seen,
            release.verdict_updated_at,
            release.first_seen,
            hours,
            settings,
            now,
        )
    body = release_out(agent, release)
    body.update(
        {
            "user_state": {
                "expected_changes": [
                    metric.value
                    for metric in sorted(user_state.expected_changes, key=lambda item: item.value)
                ],
                "manual_baseline": user_state.manual_baseline,
                "changed_at": None
                if user_state.changed_at is None
                else to_iso(user_state.changed_at),
                "stopped_at": None
                if user_state.stopped_at is None
                else to_iso(user_state.stopped_at),
            },
            "timing": {
                "since_first_seen_seconds": int((now - release.first_seen).total_seconds()),
                "until_max_window_seconds": int(
                    (release.first_seen + timedelta(hours=hours) - now).total_seconds()
                ),
                "last_check_at": None if latest is None else to_iso(latest.evaluated_at),
                "next_check_at": None if next_check is None else to_iso(next_check),
            },
            "evaluation": None if latest is None else evaluation_out(latest, include_slices=True),
            "summary": verdict_document(agent, release, settings),
            "coverage": None
            if latest is None
            else metric_coverage(agent, latest.metrics.get("items")),
            "actions": {
                "baseline": {"enabled": not release.final},
                "stop": {"enabled": not release.final and user_state.stopped_at is None},
                "expected_changes": {
                    "enabled": trace_window_stored(
                        release.first_seen, now, await stored_trace_days(meta)
                    )
                },
            },
        }
    )
    return body


def verdict_document(agent: Agent, release: Release, settings: Any) -> dict[str, Any]:
    if release.verdict_summary:
        return release.verdict_summary
    summary = pending_summary(agent, release, settings)
    if release.state is VerdictState.PENDING:
        summary["verdict"] = VerdictState.PENDING.value
    return summary
