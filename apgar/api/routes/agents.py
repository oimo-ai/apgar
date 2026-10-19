from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query, Request, Response

from apgar.agent_config import AgentConfigError, build_agent
from apgar.api.deps import authorize, configured_keys_cache
from apgar.api.errors import ApiError
from apgar.api.present import agent_out
from apgar.api.schemas import AgentIn, AgentPatch, MetricIn
from apgar.domain.enums import Source
from apgar.domain.models import Agent, IngestToken, Release
from apgar.storage.interfaces import MetaStore
from apgar.storage.types import ReleaseFilters
from apgar.verdict.coverage import metric_coverage

router = APIRouter()
_COVERAGE_LOOKBACK = 3


def _metric_map(raw: dict[str, MetricIn] | None) -> dict[str, Any] | None:
    if raw is None:
        return None
    return {key: item.model_dump(mode="json", exclude_none=True) for key, item in raw.items()}


def _from(spec: object) -> str | None:
    if spec is None:
        return None
    value = getattr(spec, "from_attribute", None)
    return value if isinstance(value, str) or value is None else None


async def _render(request: Request, agent: Agent) -> dict[str, Any]:
    now = request.app.state.clock()
    meta = request.app.state.meta_store
    activity = await request.app.state.event_store.agent_activity(agent.id, now)
    releases = await meta.list_releases(ReleaseFilters(agent_id=agent.id, limit=100_000, offset=0))
    latest = max(releases, key=lambda item: item.first_seen) if releases else None
    included = agent.source is Source.langfuse and bool(agent.langfuse_connection_id)
    sync = await meta.get_sync_state(agent.langfuse_connection_id) if included else None
    return agent_out(
        agent,
        activity,
        latest,
        sync,
        sync_included=included,
        coverage=await _coverage(meta, agent, releases),
    )


async def _coverage(meta: MetaStore, agent: Agent, seen: list[Release]) -> dict[str, Any] | None:
    recent = sorted(seen, key=lambda item: item.last_seen or item.updated_at, reverse=True)
    for release in recent[:_COVERAGE_LOOKBACK]:
        evaluations = await meta.list_evaluations(agent.id, release.release, limit=1)
        coverage = (
            metric_coverage(agent, evaluations[0].metrics.get("items")) if evaluations else None
        )
        if coverage is not None:
            return coverage
    return None


async def _save(request: Request, agent: Agent) -> dict[str, Any]:
    await request.app.state.meta_store.upsert_agent(agent)
    configured_keys_cache(request).invalidate()
    return await _render(request, agent)


@router.get("/api/v1/agents")
async def list_agents(
    request: Request,
    include_demo: bool = True,
    limit: int = Query(default=50, ge=0, le=500),
    offset: int = Query(default=0, ge=0),
) -> dict[str, object]:
    await authorize(request)
    agents = await request.app.state.meta_store.list_agents(include_demo=include_demo)
    page = agents[offset : offset + limit]
    items = [await _render(request, agent) for agent in page]
    return {"items": items, "total": len(agents)}


@router.post("/api/v1/agents", status_code=201)
async def create_agent(request: Request, body: AgentIn) -> dict[str, Any]:
    await authorize(request)
    meta = request.app.state.meta_store
    if await meta.get_agent_by_name(body.name) is not None:
        raise ApiError("conflict", 409, "agent name already exists")
    now = request.app.state.clock()
    try:
        agent = await build_agent(
            meta,
            name=body.name,
            source=body.source,
            langfuse_connection=body.langfuse_connection,
            agent_filter=body.filter,
            environment=body.environment,
            release_from=_from(body.release),
            surface_from=_from(body.surface_mapping),
            output_format=body.output_format,
            slack_connection=body.slack_connection,
            metrics=_metric_map(body.metrics),
            verdict=None if body.verdict is None else body.verdict.model_dump(exclude_none=True),
            now=now,
        )
    except AgentConfigError as exc:
        raise ApiError("validation_error", 422, exc.message) from exc
    return await _save(request, agent)


@router.get("/api/v1/agents/{agent}")
async def get_agent(request: Request, agent: str) -> dict[str, Any]:
    await authorize(request)
    found = await request.app.state.meta_store.get_agent_by_name(agent)
    if found is None:
        raise ApiError("not_found", 404, "agent not found")
    return await _render(request, found)


@router.patch("/api/v1/agents/{agent}")
async def patch_agent(request: Request, agent: str, body: AgentPatch) -> dict[str, Any]:
    await authorize(request)
    meta = request.app.state.meta_store
    current = await meta.get_agent_by_name(agent)
    if current is None:
        raise ApiError("not_found", 404, "agent not found")
    fields = body.model_fields_set
    if "metrics" in fields and body.metrics is not None:
        merged = dict(current.metric_settings)
        merged.update(_metric_map(body.metrics) or {})
        metrics: dict[str, Any] | None = merged
        keep_metrics = False
    elif "metrics" in fields:
        metrics = {}
        keep_metrics = False
    else:
        metrics = None
        keep_metrics = True
    now = request.app.state.clock()
    try:
        updated = await build_agent(
            meta,
            name=current.name,
            source=current.source,
            langfuse_connection=body.langfuse_connection
            if "langfuse_connection" in fields
            else (current.langfuse_connection_id or None),
            agent_filter=body.filter if "filter" in fields else current.filter,
            environment=(
                body.environment if "environment" in fields else (current.environment or None)
            ),
            release_from=_from(body.release)
            if "release" in fields
            else current.release_settings.from_attribute,
            surface_from=_from(body.surface_mapping)
            if "surface_mapping" in fields
            else current.surface_mapping.from_attribute,
            output_format=(
                body.output_format if body.output_format is not None else current.output_format
            ),
            slack_connection=body.slack_connection
            if "slack_connection" in fields
            else (current.slack_connection_id or None),
            metrics=metrics,
            verdict=None if body.verdict is None else body.verdict.model_dump(exclude_none=True),
            now=now,
            existing=current,
            keep_metrics=keep_metrics,
            keep_verdict="verdict" not in fields,
            merge_verdict="verdict" in fields,
        )
    except AgentConfigError as exc:
        raise ApiError("validation_error", 422, exc.message) from exc
    return await _save(request, updated)


@router.delete("/api/v1/agents/{agent}", status_code=204)
async def delete_agent(request: Request, agent: str) -> Response:
    await authorize(request)
    meta = request.app.state.meta_store
    found = await meta.get_agent_by_name(agent)
    if found is None:
        raise ApiError("not_found", 404, "agent not found")
    now = request.app.state.clock()
    await meta.delete_agent(found.id, now)
    tokens = await meta.list_ingest_tokens()
    for token in tokens:
        if token.agent_id != found.id or token.revoked_at is not None:
            continue
        revoked = IngestToken(
            id=token.id,
            name=token.name,
            token_hash=token.token_hash,
            token_prefix=token.token_prefix,
            agent_id=token.agent_id,
            auto_create_agents=token.auto_create_agents,
            created_at=token.created_at,
            revoked_at=now,
            updated_at=now,
        )
        await meta.upsert_ingest_token(revoked)
    return Response(status_code=204)
