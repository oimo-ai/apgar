from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict

from apgar.api.deps import authorize
from apgar.api.errors import ApiError
from apgar.domain.retention import (
    RETENTION_DEFAULTS,
    TRACE_DATA_DAYS,
    VERDICT_HISTORY_DAYS,
    retention_value_error,
    verdict_history_error,
)
from apgar.telemetry import env_disables_telemetry, telemetry_is_enabled

router = APIRouter()


class SettingsPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    retention: dict[str, int] | None = None
    telemetry: dict[str, Any] | None = None


async def _retention(request: Request) -> dict[str, int]:
    meta = request.app.state.meta_store
    values: dict[str, int] = {}
    for key, default in RETENTION_DEFAULTS.items():
        raw = await meta.get_setting(f"retention.{key}")
        values[key] = default if raw is None else int(raw)
    return values


@router.get("/api/v1/settings")
async def get_settings(request: Request) -> dict[str, Any]:
    await authorize(request)
    meta = request.app.state.meta_store
    settings = request.app.state.settings
    return {
        "retention": await _retention(request),
        "telemetry": {
            "enabled": await telemetry_is_enabled(settings, meta),
            "disabled_by_environment": env_disables_telemetry(settings),
        },
    }


@router.patch("/api/v1/settings")
async def patch_settings(request: Request, body: SettingsPatch) -> dict[str, Any]:
    await authorize(request)
    meta = request.app.state.meta_store
    now = request.app.state.clock()
    if body.retention is not None:
        unknown = set(body.retention) - set(RETENTION_DEFAULTS)
        if unknown:
            names = ", ".join(sorted(unknown))
            raise ApiError("validation_error", 422, f"retention: unknown field {names}")
        for key in sorted(body.retention):
            error = retention_value_error(key, body.retention[key])
            if error is not None:
                raise ApiError("validation_error", 422, error)
        current = await _retention(request)
        proposed = {**current, **body.retention}
        shorter = verdict_history_error(proposed[TRACE_DATA_DAYS], proposed[VERDICT_HISTORY_DAYS])
        if shorter is not None:
            raise ApiError("validation_error", 422, shorter)
        for key, value in body.retention.items():
            await meta.set_setting(f"retention.{key}", str(value), now)
    if body.telemetry is not None:
        if "enabled" in body.telemetry:
            enabled = body.telemetry["enabled"]
            if not isinstance(enabled, bool):
                raise ApiError("validation_error", 422, "telemetry.enabled: must be a boolean")
            await meta.set_setting("telemetry.enabled", "1" if enabled else "0", now)
        if "endpoint" in body.telemetry:
            endpoint = body.telemetry["endpoint"]
            if not isinstance(endpoint, str) or not endpoint:
                raise ApiError("validation_error", 422, "telemetry.endpoint: must be a URL")
            await meta.set_setting("telemetry.endpoint", endpoint, now)
    return await get_settings(request)
