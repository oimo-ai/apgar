from __future__ import annotations

from dataclasses import replace
from typing import Any

from fastapi import APIRouter, Query, Request

from apgar.api.deps import authorize
from apgar.api.errors import ApiError
from apgar.domain.enums import NotificationStatus
from apgar.domain.time import monotonic_updated_at, to_iso
from apgar.storage.interfaces import MetaStore

router = APIRouter()


def _status(value: str | None) -> NotificationStatus | None:
    if value is None or value == "" or value == "all":
        return None
    try:
        return NotificationStatus(value)
    except ValueError as exc:
        raise ApiError("validation_error", 422, "status: must be pending, sent, or failed") from exc


async def _names(meta: MetaStore) -> dict[str, str]:
    agents = await meta.list_agents(include_demo=True, include_deleted=True)
    return {agent.id: agent.name for agent in agents}


def _out(row: Any, names: dict[str, str]) -> dict[str, Any]:
    return {
        "id": row.id,
        "agent": names.get(row.agent_id, row.agent_id),
        "release": row.release,
        "event": row.event.value,
        "channel": row.channel.value,
        "status": row.status.value,
        "attempts": row.attempts,
        "next_attempt_at": to_iso(row.next_attempt_at),
        "last_error": row.last_error or None,
        "created_at": to_iso(row.created_at),
        "updated_at": to_iso(row.updated_at),
    }


@router.get("/api/v1/notifications")
async def list_notifications(
    request: Request,
    status: str | None = None,
    limit: int = Query(default=100, ge=0, le=500),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    await authorize(request)
    meta = request.app.state.meta_store
    rows = await meta.list_notifications(_status(status), limit=10_000)
    names = await _names(meta)
    page = rows[offset : offset + limit]
    return {"items": [_out(row, names) for row in page], "total": len(rows)}


@router.post("/api/v1/notifications/{notification_id}/retry", status_code=202)
async def retry_notification(request: Request, notification_id: str) -> dict[str, str]:
    await authorize(request)
    meta = request.app.state.meta_store
    rows = await meta.list_notifications(None, limit=10_000)
    found = next((row for row in rows if row.id == notification_id), None)
    if found is None:
        raise ApiError("not_found", 404, "notification not found")
    if found.status is not NotificationStatus.failed:
        raise ApiError("conflict", 409, "only a failed notification can be retried")
    now = request.app.state.clock()
    updated = replace(
        found,
        status=NotificationStatus.pending,
        attempts=0,
        next_attempt_at=now,
        last_error="",
        updated_at=monotonic_updated_at(now, found.updated_at),
    )
    await meta.upsert_notification(updated)
    return {"status": "queued"}
