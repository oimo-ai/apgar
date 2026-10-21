from __future__ import annotations

import logging
import math
import platform
import statistics
import uuid
from datetime import UTC, date, datetime, timedelta

from apgar import __version__
from apgar.config import Settings
from apgar.domain.enums import (
    ConnectionStatus,
    ConnectionType,
    NotificationEvent,
    NotificationStatus,
    ReasonCode,
    ReleaseEventType,
    Source,
    VerdictState,
)
from apgar.domain.models import Agent, Connection, Release
from apgar.domain.settings import VerdictSettings
from apgar.domain.time import to_iso
from apgar.storage.interfaces import EventStore, MetaStore
from apgar.storage.types import ReleaseFilters

_LOG = logging.getLogger("apgar.telemetry")

# A PostHog project token can only write events, so it is safe to publish.
POSTHOG_PROJECT_TOKEN = "phc_D5NAh7ptvRRgwXzm242gn5xauhUZ4xPbotEqh2kGmk2Z"
EVENT = "apgar_daily_report"
SCHEMA = 2

_WINDOW = timedelta(hours=24)
_PAGE = 500
_DECIDED = (VerdictState.PASS, VerdictState.FAIL)
_ENDED_REASONS = (ReasonCode.window_elapsed, ReasonCode.stopped, ReasonCode.superseded)
_HOUR_BUCKETS = ((2, "<2h"), (6, "2-6h"), (24, "6-24h"), (48, "24-48h"))


def turns_per_day_magnitude(turns: int) -> int:
    if turns < 10:
        return 0
    return math.floor(math.log10(turns))


def untagged_share_bucket(untagged: int, turns: int) -> str | None:
    if turns == 0:
        return None
    if untagged == 0:
        return "0%"
    if untagged >= turns:
        return "100%"
    share = untagged / turns
    if share < 0.1:
        return "<10%"
    if share < 0.5:
        return "10-49%"
    return "50-99%"


def hours_bucket(hours: float) -> str:
    for limit, label in _HOUR_BUCKETS:
        if hours < limit:
            return label
    return "48h+"


def env_disables_telemetry(settings: Settings) -> bool:
    return str(settings.telemetry) == "0"


def log_startup(settings: Settings) -> None:
    if env_disables_telemetry(settings):
        _LOG.info("telemetry disabled")


def _today(now: datetime) -> date:
    aware = now if now.tzinfo is not None else now.replace(tzinfo=UTC)
    return aware.astimezone(UTC).date()


async def telemetry_is_enabled(settings: Settings, meta_store: MetaStore) -> bool:
    if env_disables_telemetry(settings):
        return False
    stored = await meta_store.get_setting("telemetry.enabled")
    return stored != "0"


async def record_config_file(meta_store: MetaStore, present: bool, now: datetime) -> None:
    await meta_store.set_setting("telemetry.config_file", "1" if present else "0", now)


async def _stored(meta_store: MetaStore, key: str, value: str, now: datetime) -> str:
    stored = await meta_store.get_setting(key)
    if stored:
        return stored
    await meta_store.set_setting(key, value, now)
    return value


async def _releases(meta_store: MetaStore, agent_id: str) -> list[Release]:
    rows: list[Release] = []
    offset = 0
    while True:
        page = await meta_store.list_releases(
            ReleaseFilters(agent_id=agent_id, limit=_PAGE, offset=offset)
        )
        rows.extend(page)
        if len(page) < _PAGE:
            return rows
        offset += _PAGE


def _agent_properties(live: list[Agent]) -> dict[str, object]:
    defaults = VerdictSettings()
    return {
        "agents_otlp": sum(1 for agent in live if agent.source is Source.otlp),
        "agents_langfuse": sum(1 for agent in live if agent.source is Source.langfuse),
        "agents_custom_verdict": sum(1 for agent in live if agent.verdict_settings != defaults),
        "agents_custom_metrics": sum(1 for agent in live if agent.metric_settings),
    }


async def _activity_properties(
    event_store: EventStore, live: list[Agent], now: datetime
) -> dict[str, object]:
    turns = 0
    untagged = 0
    idle = 0
    for agent in live:
        activity = await event_store.agent_activity(agent.id, now)
        turns += activity.turns_24h
        untagged += activity.untagged_24h
        if activity.turns_24h == 0:
            idle += 1
    return {
        "turns_per_day_magnitude": turns_per_day_magnitude(turns),
        "untagged_share": untagged_share_bucket(untagged, turns),
        "agents_without_turns_24h": idle,
    }


def _connection_properties(connections: list[Connection]) -> dict[str, object]:
    counts = {f"connections_{kind.value}": 0 for kind in ConnectionType}
    for connection in connections:
        counts[f"connections_{connection.type.value}"] += 1
    errors = sum(
        1
        for connection in connections
        if connection.type is ConnectionType.langfuse
        and connection.status is ConnectionStatus.error
    )
    return {**counts, "langfuse_connections_error": errors}


def _ended_key(release: Release) -> str | None:
    if release.state in _DECIDED:
        return release.state.value.lower()
    if release.reason in _ENDED_REASONS:
        return release.reason.value
    return None


async def _release_properties(
    meta_store: MetaStore, live: list[Agent], since: datetime
) -> dict[str, object]:
    states = {f"releases_{state.value.lower()}": 0 for state in VerdictState}
    ended_keys = [state.value.lower() for state in _DECIDED] + [r.value for r in _ENDED_REASONS]
    ended = {f"releases_ended_24h_{key}": 0 for key in ended_keys}
    detected = 0
    hours: list[float] = []
    for agent in live:
        for release in await _releases(meta_store, agent.id):
            states[f"releases_{release.state.value.lower()}"] += 1
            if release.first_seen >= since:
                detected += 1
            if not release.final or release.final_at is None or release.final_at < since:
                continue
            key = _ended_key(release)
            if key is None:
                continue
            ended[f"releases_ended_24h_{key}"] += 1
            if release.state not in _DECIDED:
                continue
            first = await meta_store.first_evaluation(agent.id, release.release, release.state)
            if first is not None:
                hours.append((first.evaluated_at - release.first_seen).total_seconds() / 3600)
    return {
        **states,
        "releases_detected_24h": detected,
        **ended,
        "hours_to_verdict": hours_bucket(statistics.median(hours)) if hours else None,
    }


async def _event_properties(
    meta_store: MetaStore, live_ids: set[str], since: datetime
) -> dict[str, object]:
    counts = {f"release_events_24h_{kind.value}": 0 for kind in ReleaseEventType}
    for event in await meta_store.release_events_since(since):
        if event.agent_id in live_ids:
            counts[f"release_events_24h_{event.type.value}"] += 1
    return dict(counts)


async def _notification_properties(
    meta_store: MetaStore, live_ids: set[str], since: datetime
) -> dict[str, object]:
    counts = {f"notifications_24h_{event.value}": 0 for event in NotificationEvent}
    counts.update({f"notifications_24h_{status.value}": 0 for status in NotificationStatus})
    rows = await meta_store.list_notifications(None, limit=100_000, created_since=since)
    for row in rows:
        if row.agent_id not in live_ids:
            continue
        counts[f"notifications_24h_{row.event.value}"] += 1
        counts[f"notifications_24h_{row.status.value}"] += 1
    return dict(counts)


async def build_payload(
    meta_store: MetaStore,
    event_store: EventStore,
    settings: Settings,
    now: datetime,
) -> dict[str, object]:
    del settings
    today = _today(now)
    instance_id = await _stored(meta_store, "telemetry.instance_id", str(uuid.uuid4()), now)
    created = await _stored(meta_store, "telemetry.created_date", today.isoformat(), now)
    since = now - _WINDOW
    agents = await meta_store.list_agents()
    live = [agent for agent in agents if not agent.is_demo]
    live_ids = {agent.id for agent in live}
    properties: dict[str, object] = {
        "$process_person_profile": False,
        "$geoip_disable": True,
        "schema": SCHEMA,
        "version": __version__,
        "os": platform.system().lower(),
        "arch": platform.machine().lower(),
        "install_age_days": max(0, (today - date.fromisoformat(created)).days),
        "uses_config_file": await meta_store.get_setting("telemetry.config_file") == "1",
        "agents_non_demo": len(live),
        "agents_demo": len(agents) - len(live),
    }
    properties.update(_agent_properties(live))
    properties.update(await _activity_properties(event_store, live, now))
    properties.update(_connection_properties(await meta_store.list_connections()))
    properties.update(await _release_properties(meta_store, live, since))
    properties.update(await _event_properties(meta_store, live_ids, since))
    properties.update(await _notification_properties(meta_store, live_ids, since))
    return {
        "api_key": POSTHOG_PROJECT_TOKEN,
        "event": EVENT,
        "distinct_id": instance_id,
        "timestamp": to_iso(now),
        "properties": properties,
    }


def report_day(now: datetime) -> str:
    return _today(now).isoformat()
