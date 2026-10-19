from __future__ import annotations

import re
from datetime import datetime
from typing import Any
from uuid import uuid4

from pydantic import ValidationError

from apgar.domain.enums import ConnectionType, MetricId, OutputFormat, Source
from apgar.domain.models import Agent
from apgar.domain.settings import (
    DEFAULT_METRICS,
    AgentFilter,
    MetricSettings,
    ReleaseSettings,
    SurfaceMapping,
    VerdictSettings,
    effective_metric_settings,
)
from apgar.storage.interfaces import MetaStore

_SLUG = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_METRIC_FIELDS = {"enabled", "direction", "tolerance_mode", "tolerance", "role"}
_VERDICT_FIELDS = {
    "min_turns",
    "min_sessions",
    "min_turns_slice",
    "fail_confirmations",
    "pass_confirmations",
    "max_window_hours",
    "include_mixed_sessions",
    "alpha",
    "notify_healthy",
}


class AgentConfigError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def _metrics(raw: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    if not raw:
        return {}
    cleaned: dict[str, dict[str, Any]] = {}
    for key, value in raw.items():
        if key not in MetricId._value2member_map_:
            raise AgentConfigError(f"metrics.{key}: unknown metric id")
        if not isinstance(value, dict):
            raise AgentConfigError(f"metrics.{key}: expected an object")
        unknown = set(value) - _METRIC_FIELDS
        if unknown:
            names = ", ".join(sorted(unknown))
            raise AgentConfigError(f"metrics.{key}: unknown field {names}")
        base = DEFAULT_METRICS[MetricId(key)].model_dump(mode="json")
        base.update(value)
        try:
            MetricSettings.model_validate(base)
        except ValidationError as exc:
            raise AgentConfigError(f"metrics.{key}: {exc.errors()[0]['msg']}") from exc
        cleaned[key] = {
            item_key: item_value for item_key, item_value in value.items() if item_value is not None
        }
    return cleaned


def _verdict(raw: dict[str, Any] | None, base: VerdictSettings | None = None) -> VerdictSettings:
    data = (base or VerdictSettings()).model_dump(mode="json")
    if raw:
        unknown = set(raw) - _VERDICT_FIELDS
        if unknown:
            names = ", ".join(sorted(unknown))
            raise AgentConfigError(f"verdict: unknown field {names}")
        data.update({key: value for key, value in raw.items() if value is not None})
    try:
        parsed = VerdictSettings.model_validate(data)
    except ValidationError as exc:
        error = exc.errors()[0]
        field = ".".join(str(part) for part in error["loc"])
        raise AgentConfigError(f"verdict.{field}: {error['msg']}") from exc
    if not 0 < parsed.alpha <= 0.5:
        raise AgentConfigError("verdict.alpha: must be in (0, 0.5]")
    return parsed


def _filter_useful(agent_filter: AgentFilter) -> bool:
    if agent_filter.trace_name:
        return True
    if agent_filter.tags:
        return True
    return bool(agent_filter.metadata)


def _blank(value: str | None) -> str:
    return "" if value is None else value


async def _require_connection(
    meta: MetaStore,
    connection_id: str | None,
    expected: ConnectionType,
    field: str,
) -> str:
    if not connection_id:
        raise AgentConfigError(f"{field}: is required")
    connection = await meta.get_connection(connection_id)
    if connection is None or connection.type is not expected:
        raise AgentConfigError(f"{field}: must reference a {expected.value} connection")
    return connection.id


async def build_agent(
    meta: MetaStore,
    *,
    name: str,
    source: Source,
    langfuse_connection: str | None,
    agent_filter: AgentFilter | None,
    environment: str | None,
    release_from: str | None,
    surface_from: str | None,
    output_format: OutputFormat,
    slack_connection: str | None,
    metrics: dict[str, Any] | None,
    verdict: dict[str, Any] | None,
    now: datetime,
    existing: Agent | None = None,
    keep_metrics: bool = False,
    keep_verdict: bool = False,
    merge_verdict: bool = False,
) -> Agent:
    if _SLUG.fullmatch(name) is None:
        raise AgentConfigError("name: must match ^[a-z0-9][a-z0-9._-]{0,63}$")
    if source is Source.otlp:
        if langfuse_connection is not None:
            raise AgentConfigError("langfuse_connection: must be null")
        if agent_filter is not None:
            raise AgentConfigError("filter: must be null")
        langfuse_id = ""
    else:
        langfuse_id = await _require_connection(
            meta, langfuse_connection, ConnectionType.langfuse, "langfuse_connection"
        )
        if agent_filter is None or not _filter_useful(agent_filter):
            raise AgentConfigError("filter: must include trace_name, tags, or metadata")
    slack_id = ""
    if slack_connection is not None:
        slack_id = await _require_connection(
            meta, slack_connection, ConnectionType.slack, "slack_connection"
        )
    if keep_metrics and existing is not None:
        metric_settings = existing.metric_settings
    else:
        metric_settings = _metrics(metrics)
    if keep_verdict and existing is not None:
        verdict_settings = existing.verdict_settings
    else:
        base = existing.verdict_settings if merge_verdict and existing is not None else None
        verdict_settings = _verdict(verdict, base)
    created_at = now if existing is None else existing.created_at
    return Agent(
        id=str(uuid4()) if existing is None else existing.id,
        name=name,
        source=source,
        langfuse_connection_id=langfuse_id,
        filter=agent_filter,
        environment=_blank(environment),
        surface_mapping=SurfaceMapping(from_attribute=surface_from),
        release_settings=ReleaseSettings(from_attribute=release_from),
        metric_settings=metric_settings,
        verdict_settings=verdict_settings,
        output_format=output_format,
        slack_connection_id=slack_id,
        is_demo=False if existing is None else existing.is_demo,
        created_at=created_at,
        updated_at=now,
        deleted_at=None if existing is None else existing.deleted_at,
    )


def merged_metrics(agent: Agent) -> dict[str, dict[str, Any]]:
    return {
        metric_id.value: settings.model_dump(mode="json")
        for metric_id, settings in effective_metric_settings(agent.metric_settings).items()
    }
