from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from typing import Any
from uuid import uuid4

import httpx
from fastapi import APIRouter, Query, Request, Response

from apgar.actions.messages import webhook_test_payload
from apgar.actions.webhook import send_webhook
from apgar.api.deps import authorize
from apgar.api.errors import ApiError
from apgar.api.present import connection_out
from apgar.api.schemas import ConnectionIn, ConnectionPatch
from apgar.connection_config import ConnectionConfigError, parse_config
from apgar.domain.enums import ConnectionStatus, ConnectionType
from apgar.domain.models import Connection

router = APIRouter()


def _config_dict(raw: dict[str, object]) -> dict[str, Any]:
    parsed: dict[str, Any] = {}
    for key, value in raw.items():
        parsed[str(key)] = value
    return parsed


async def _referenced(request: Request, connection_id: str) -> bool:
    agents = await request.app.state.meta_store.list_agents(include_demo=True, include_deleted=True)
    return any(
        agent.langfuse_connection_id == connection_id or agent.slack_connection_id == connection_id
        for agent in agents
    )


async def _probe(
    connection: Connection,
    now: datetime,
) -> tuple[str, str, dict[str, Any]]:
    config = dict(connection.config)
    detail = "ok"
    ok = False
    try:
        async with httpx.AsyncClient(timeout=10) as http:
            if connection.type is ConnectionType.langfuse:
                host = str(config["host"]).rstrip("/")
                response = await http.get(
                    f"{host}/api/public/projects",
                    auth=(str(config["public_key"]), str(config["secret_key"])),
                )
                if response.status_code != 200:
                    detail = f"HTTP {response.status_code}"
                else:
                    payload = response.json()
                    data = payload.get("data") if isinstance(payload, dict) else None
                    if not isinstance(data, list) or not data or not isinstance(data[0], dict):
                        detail = "projects response was empty"
                    else:
                        project_id = data[0].get("id")
                        if not isinstance(project_id, str) or not project_id:
                            detail = "projects response was empty"
                        else:
                            config["project_id"] = project_id
                            ok = True
            elif connection.type is ConnectionType.slack:
                response = await http.post(
                    str(config["webhook_url"]),
                    json={"text": "Apgar connection test"},
                )
                if response.status_code == 200:
                    ok = True
                else:
                    detail = f"HTTP {response.status_code}"
            else:
                await send_webhook(
                    http,
                    str(config["url"]),
                    str(config["secret"]),
                    webhook_test_payload(now),
                    now,
                )
                ok = True
    except Exception as exc:
        detail = str(exc)
        ok = False
    status = "ok" if ok else "error"
    return status, detail[:500], config


@router.get("/api/v1/connections")
async def list_connections(
    request: Request,
    limit: int = Query(default=50, ge=0, le=500),
    offset: int = Query(default=0, ge=0),
) -> dict[str, object]:
    await authorize(request)
    rows = await request.app.state.meta_store.list_connections()
    page = rows[offset : offset + limit]
    return {"items": [connection_out(item) for item in page], "total": len(rows)}


@router.post("/api/v1/connections", status_code=201)
async def create_connection(request: Request, body: ConnectionIn) -> dict[str, Any]:
    await authorize(request)
    settings = request.app.state.settings
    try:
        config = parse_config(
            body.type,
            _config_dict(body.config),
            allow_insecure_slack=settings.allow_insecure_slack,
        )
    except ConnectionConfigError as exc:
        raise ApiError("validation_error", 422, exc.message) from exc
    now = request.app.state.clock()
    connection = Connection(
        id=str(uuid4()),
        name=body.name,
        type=body.type,
        config=config,
        status=ConnectionStatus.untested,
        last_checked_at=None,
        last_error="",
        created_at=now,
        updated_at=now,
    )
    await request.app.state.meta_store.upsert_connection(connection)
    return connection_out(connection)


@router.patch("/api/v1/connections/{connection_id}")
async def patch_connection(
    request: Request, connection_id: str, body: ConnectionPatch
) -> dict[str, Any]:
    await authorize(request)
    meta = request.app.state.meta_store
    current = await meta.get_connection(connection_id)
    if current is None:
        raise ApiError("not_found", 404, "connection not found")
    config = current.config
    if body.config is not None:
        settings = request.app.state.settings
        try:
            config = parse_config(
                current.type,
                _config_dict(body.config),
                allow_insecure_slack=settings.allow_insecure_slack,
                previous=current.config,
            )
        except ConnectionConfigError as exc:
            raise ApiError("validation_error", 422, exc.message) from exc
    now = request.app.state.clock()
    updated = replace(
        current,
        name=body.name if body.name is not None else current.name,
        config=config,
        updated_at=now,
    )
    await meta.upsert_connection(updated)
    return connection_out(updated)


@router.delete("/api/v1/connections/{connection_id}", status_code=204)
async def delete_connection(request: Request, connection_id: str) -> Response:
    await authorize(request)
    meta = request.app.state.meta_store
    current = await meta.get_connection(connection_id)
    if current is None:
        raise ApiError("not_found", 404, "connection not found")
    if await _referenced(request, connection_id):
        raise ApiError("conflict", 409, "connection is referenced by an agent")
    await meta.delete_connection(connection_id, request.app.state.clock())
    return Response(status_code=204)


@router.post("/api/v1/connections/{connection_id}/test")
async def test_connection(request: Request, connection_id: str) -> dict[str, str]:
    await authorize(request)
    meta = request.app.state.meta_store
    current = await meta.get_connection(connection_id)
    if current is None:
        raise ApiError("not_found", 404, "connection not found")
    now = request.app.state.clock()
    status, detail, config = await _probe(current, now)
    updated = replace(
        current,
        config=config,
        status=ConnectionStatus.ok if status == "ok" else ConnectionStatus.error,
        last_checked_at=now,
        last_error="" if status == "ok" else detail,
        updated_at=now,
    )
    await meta.upsert_connection(updated)
    return {"status": status, "detail": detail if status == "error" else "ok"}
