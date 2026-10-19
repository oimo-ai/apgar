from __future__ import annotations

from datetime import timedelta
from typing import Any

from apgar.agent_config import merged_metrics
from apgar.connection_config import redact_config
from apgar.domain.models import Agent, Connection, Release, SyncState
from apgar.domain.time import to_iso
from apgar.storage.types import AgentActivity
from apgar.verdict.coverage import behavior_low


def _null(value: str) -> str | None:
    return value or None


def agent_out(
    agent: Agent,
    activity: AgentActivity,
    latest: Release | None,
    sync: SyncState | None,
    *,
    sync_included: bool,
    coverage: dict[str, Any] | None = None,
) -> dict[str, Any]:
    turns = activity.turns_24h
    share = 0.0 if turns == 0 else activity.untagged_24h / turns
    warnings: list[str] = []
    if share > 0.05:
        warnings.append("untagged_share")
    if agent.environment == "" and len(activity.environments_24h) > 1:
        warnings.append("multiple_environments")
    if behavior_low(coverage):
        warnings.append("behavior_coverage")
    sync_block: dict[str, Any] | None = None
    if sync_included:
        if sync is None or (sync.last_success_at is None and sync.last_error == ""):
            status = "never"
        elif sync.last_error:
            status = "error"
        else:
            status = "ok"
        if sync is not None and sync.last_error:
            warnings.append("sync_error")
        sync_block = {
            "status": status,
            "watermark": None if sync is None or sync.watermark is None else to_iso(sync.watermark),
            "last_success_at": None
            if sync is None or sync.last_success_at is None
            else to_iso(sync.last_success_at),
            "lag_seconds": None if sync is None else sync.lag_seconds,
            "last_error": "" if sync is None else sync.last_error,
        }
    agent_filter = None if agent.filter is None else agent.filter.model_dump(mode="json")
    latest_block = None
    if latest is not None:
        latest_block = {
            "release": latest.release,
            "state": latest.state.value,
            "reason": latest.reason.value,
            "final": latest.final,
            "first_seen": to_iso(latest.first_seen),
            "early": bool(latest.verdict_summary.get("early")),
            "failing_metrics": failing_metrics_out(latest),
        }
    return {
        "name": agent.name,
        "source": agent.source.value,
        "langfuse_connection": _null(agent.langfuse_connection_id),
        "filter": agent_filter,
        "environment": _null(agent.environment),
        "release": {"from": agent.release_settings.from_attribute},
        "surface_mapping": {"from": agent.surface_mapping.from_attribute},
        "output_format": agent.output_format.value,
        "slack_connection": _null(agent.slack_connection_id),
        "metrics": agent.metric_settings,
        "verdict": agent.verdict_settings.model_dump(mode="json"),
        "id": agent.id,
        "is_demo": agent.is_demo,
        "created_at": to_iso(agent.created_at),
        "updated_at": to_iso(agent.updated_at),
        "effective_metrics": merged_metrics(agent),
        "effective_verdict": agent.verdict_settings.model_dump(mode="json"),
        "activity": {
            "turns_24h": activity.turns_24h,
            "untagged_share_24h": share,
            "environments_24h": activity.environments_24h,
            "last_turn_at": None
            if activity.last_turn_at is None
            else to_iso(activity.last_turn_at),
        },
        "latest_release": latest_block,
        "coverage": coverage,
        "sync": sync_block,
        "warnings": warnings,
    }


def failing_metrics_out(release: Release) -> list[dict[str, str]]:
    failed = release.verdict_summary.get("failed_metrics")
    if not isinstance(failed, list):
        return []
    return [
        {"id": str(item.get("id", "")), "headline": str(item.get("headline", ""))}
        for item in failed
        if isinstance(item, dict)
    ]


def connection_out(connection: Connection) -> dict[str, Any]:
    return {
        "id": connection.id,
        "name": connection.name,
        "type": connection.type.value,
        "status": connection.status.value,
        "last_checked_at": None
        if connection.last_checked_at is None
        else to_iso(connection.last_checked_at),
        "last_error": connection.last_error or None,
        "created_at": to_iso(connection.created_at),
        "updated_at": to_iso(connection.updated_at),
        "config": redact_config(connection.type, connection.config),
    }


def release_out(agent: Agent, release: Release) -> dict[str, Any]:
    hours = agent.verdict_settings.max_window_hours
    return {
        "agent": agent.name,
        "agent_is_demo": agent.is_demo,
        "release": release.release,
        "first_seen": to_iso(release.first_seen),
        "last_seen": None if release.last_seen is None else to_iso(release.last_seen),
        "turn_count": release.turn_count,
        "state": release.state.value,
        "reason": release.reason.value,
        "final": release.final,
        "final_at": None if release.final_at is None else to_iso(release.final_at),
        "early": bool(release.verdict_summary.get("early")),
        "failing_metrics": failing_metrics_out(release),
        "baseline": {
            "release": _null(release.selected_baseline_release),
            "mode": _null(release.selected_baseline_mode),
            "unverified": release.baseline_unverified,
        },
        "verdict_updated_at": None
        if release.verdict_updated_at is None
        else to_iso(release.verdict_updated_at),
        "max_window_end": to_iso(release.first_seen + timedelta(hours=hours)),
    }
