from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query, Request

from apgar.api.deps import authorize
from apgar.api.errors import ApiError
from apgar.api.present import release_out
from apgar.api.schemas import BaselineIn, ExpectedChangesIn, StopIn
from apgar.api.verdict_api import (
    enqueue,
    evaluation_out,
    event_out,
    parse_body,
    release_detail,
    release_or_404,
    require_trace_window,
)
from apgar.domain.enums import JobRequestKind, ReleaseEventType
from apgar.domain.models import ReleaseEvent
from apgar.storage.types import ReleaseFilters
from apgar.verdict.state_machine import fold_events

router = APIRouter()


async def _agent_or_404(request: Request, name: str) -> Any:
    agent = await request.app.state.meta_store.get_agent_by_name(name)
    if agent is None:
        raise ApiError("not_found", 404, "agent not found")
    return agent


@router.get("/api/v1/agents/{agent}/releases")
async def list_agent_releases(
    request: Request,
    agent: str,
    limit: int = Query(default=50, ge=0, le=500),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    await authorize(request)
    found = await _agent_or_404(request, agent)
    rows = await request.app.state.meta_store.list_releases(
        ReleaseFilters(agent_id=found.id, limit=100_000, offset=0)
    )
    rows.sort(key=lambda item: (item.first_seen, item.release), reverse=True)
    page = rows[offset : offset + limit]
    return {"items": [release_out(found, item) for item in page], "total": len(rows)}


@router.get("/api/v1/agents/{agent}/releases/{release}")
async def get_release(request: Request, agent: str, release: str) -> dict[str, Any]:
    await authorize(request)
    found = await _agent_or_404(request, agent)
    row = await release_or_404(request, found, release)
    return await release_detail(request, found, row)


@router.post("/api/v1/agents/{agent}/releases/{release}/baseline", status_code=202)
async def set_baseline(request: Request, agent: str, release: str) -> dict[str, str]:
    await authorize(request)
    found = await _agent_or_404(request, agent)
    row = await release_or_404(request, found, release)
    body = await parse_body(request, BaselineIn)
    if row.final:
        raise ApiError("not_allowed", 400, "monitoring has already ended")
    if body.release == release:
        raise ApiError("not_allowed", 400, "baseline release must differ from the candidate")
    named = await request.app.state.meta_store.get_release(found.id, body.release)
    if named is None:
        raise ApiError("not_found", 404, "baseline release not found")
    if named.first_seen >= row.first_seen:
        raise ApiError(
            "not_allowed", 400, "baseline release must have been seen before the candidate"
        )
    now = request.app.state.clock()
    await request.app.state.meta_store.append_release_event(
        ReleaseEvent(
            agent_id=found.id,
            release=release,
            ts=now,
            type=ReleaseEventType.manual_baseline,
            payload={"release": body.release},
            actor=body.actor or "",
        )
    )
    await enqueue(request, found.id, release, JobRequestKind.apply_events, {})
    return {"status": "queued"}


@router.post("/api/v1/agents/{agent}/releases/{release}/expected-changes", status_code=202)
async def expected_changes(request: Request, agent: str, release: str) -> dict[str, str]:
    await authorize(request)
    found = await _agent_or_404(request, agent)
    row = await release_or_404(request, found, release)
    await require_trace_window(request, row)
    body = await parse_body(request, ExpectedChangesIn)
    now = request.app.state.clock()
    await request.app.state.meta_store.append_release_event(
        ReleaseEvent(
            agent_id=found.id,
            release=release,
            ts=now,
            type=ReleaseEventType.expected_changes,
            payload={"metrics": [metric.value for metric in body.metrics]},
            actor=body.actor or "",
        )
    )
    await enqueue(request, found.id, release, JobRequestKind.apply_events, {})
    return {"status": "queued"}


@router.post("/api/v1/agents/{agent}/releases/{release}/stop", status_code=202)
async def stop_monitoring(request: Request, agent: str, release: str) -> dict[str, str]:
    await authorize(request)
    found = await _agent_or_404(request, agent)
    row = await release_or_404(request, found, release)
    body = StopIn() if not await request.body() else await parse_body(request, StopIn)
    if row.final:
        raise ApiError("not_allowed", 400, "monitoring has already ended")
    meta = request.app.state.meta_store
    if fold_events(await meta.release_events(found.id, release)).stopped_at is not None:
        raise ApiError("not_allowed", 400, "monitoring is already stopping")
    now = request.app.state.clock()
    await meta.append_release_event(
        ReleaseEvent(
            agent_id=found.id,
            release=release,
            ts=now,
            type=ReleaseEventType.stop,
            payload={},
            actor=body.actor or "",
        )
    )
    await enqueue(request, found.id, release, JobRequestKind.apply_events, {})
    return {"status": "queued"}


@router.get("/api/v1/agents/{agent}/releases/{release}/events")
async def release_events(request: Request, agent: str, release: str) -> dict[str, Any]:
    await authorize(request)
    found = await _agent_or_404(request, agent)
    await release_or_404(request, found, release)
    events = await request.app.state.meta_store.release_events(found.id, release)
    return {"items": [event_out(event) for event in events]}


@router.get("/api/v1/agents/{agent}/releases/{release}/evaluations")
async def list_evaluations(
    request: Request,
    agent: str,
    release: str,
    limit: int = Query(default=50, ge=0, le=500),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    await authorize(request)
    found = await _agent_or_404(request, agent)
    await release_or_404(request, found, release)
    rows = await request.app.state.meta_store.list_evaluations(found.id, release, limit=100_000)
    page = rows[offset : offset + limit]
    return {
        "items": [evaluation_out(item, include_slices=False) for item in page],
        "total": len(rows),
    }
