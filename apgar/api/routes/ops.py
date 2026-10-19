from __future__ import annotations

import asyncio
import json
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import Response
from prometheus_client import CONTENT_TYPE_PLAIN_0_0_4

from apgar import __version__
from apgar.api.errors import CompactJSONResponse
from apgar.api.metrics import render_metrics
from apgar.domain.time import from_iso
from apgar.storage.clickhouse.migrate import EXPECTED_SCHEMA_VERSION
from apgar.storage.interfaces import MetaStore
from apgar.worker.heartbeat import HEARTBEAT_KEY

router = APIRouter()


def _meta(request: Request) -> MetaStore:
    store: MetaStore = request.app.state.meta_store
    return store


def _clock(request: Request) -> datetime:
    clock = request.app.state.clock
    now: datetime = clock()
    return now


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readyz")
async def readyz(request: Request) -> CompactJSONResponse:
    try:
        version = await asyncio.wait_for(_meta(request).schema_version(), timeout=2.0)
    except Exception:
        return CompactJSONResponse(
            status_code=503,
            content={"status": "unavailable", "reason": "storage_unavailable"},
        )
    if version != EXPECTED_SCHEMA_VERSION:
        return CompactJSONResponse(
            status_code=503,
            content={"status": "unavailable", "reason": "schema_mismatch"},
        )
    return CompactJSONResponse({"status": "ok", "schema_version": version})


@router.get("/metrics")
async def metrics() -> Response:
    body = await asyncio.to_thread(render_metrics)
    return Response(content=body, media_type=CONTENT_TYPE_PLAIN_0_0_4)


@router.get("/api/v1/status")
async def status(request: Request) -> dict[str, Any]:
    settings = request.app.state.settings
    body: dict[str, Any] = {
        "version": __version__,
        "storage": "ok",
        "schema_version": None,
        "worker_heartbeat_age_seconds": None,
        "demo_agents": 0,
        "demo_seeding": False,
        "public_url": settings.public_url,
    }
    meta = _meta(request)
    try:
        body["schema_version"] = await meta.schema_version()
    except Exception:
        body["storage"] = "unavailable"
        return body
    try:
        raw = await meta.get_setting(HEARTBEAT_KEY)
    except Exception:
        body["storage"] = "unavailable"
        raw = None
    if raw:
        try:
            payload = json.loads(raw)
            seen = from_iso(str(payload["ts"]))
            body["worker_heartbeat_age_seconds"] = (_clock(request) - seen).total_seconds()
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            body["worker_heartbeat_age_seconds"] = None
    try:
        agents = await meta.list_agents()
    except Exception:
        body["demo_agents"] = 0
        body["storage"] = "unavailable"
    else:
        body["demo_agents"] = sum(1 for agent in agents if agent.is_demo)
    try:
        pending = await meta.pending_jobs(limit=500)
    except Exception:
        body["demo_seeding"] = False
    else:
        from apgar.domain.enums import JobRequestKind

        body["demo_seeding"] = any(job.kind is JobRequestKind.demo_seed for job in pending)
    return body
