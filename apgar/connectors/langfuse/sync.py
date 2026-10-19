from __future__ import annotations

import json
import logging
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Any

from prometheus_client import Counter, Gauge

from apgar.config import Settings
from apgar.connectors.langfuse.client import (
    LangfuseClient,
    LangfuseClientError,
)
from apgar.connectors.langfuse.mapper import to_span_row
from apgar.domain.enums import Source
from apgar.domain.models import Agent, Connection, SpanRow, SyncState
from apgar.domain.time import to_iso
from apgar.ingest.pipeline import write_batch
from apgar.normalize.normalizer import HmacKeys, MalformedSpan
from apgar.storage.interfaces import EventStore, MetaStore

_LOG = logging.getLogger("apgar.langfuse")
LOOKBACK = timedelta(minutes=30)
SAFETY_LAG = timedelta(minutes=2)
INITIAL_BACKFILL = timedelta(hours=24)
BATCH = 50
_WRITE_CHUNK = 2000

FETCHED = Counter(
    "apgar_langfuse_observations_fetched_total",
    "Langfuse observations fetched.",
    ["connection"],
)
OVERLAP = Counter(
    "apgar_langfuse_filter_overlap_total",
    "Traces claimed by more than one agent filter.",
    ["connection"],
)
LAG = Gauge(
    "apgar_connector_lag_seconds",
    "Langfuse connector lag in seconds.",
    ["connection"],
)


@dataclass(slots=True)
class SyncResult:
    observations: int = 0
    traces: int = 0
    spans_written: int = 0
    window_start: datetime | None = None
    window_end: datetime | None = None
    skipped: bool = False


def _with_cursor(params: list[tuple[str, str]], cursor: str | None) -> list[tuple[str, str]]:
    if not cursor:
        return list(params)
    return [*params, ("cursor", cursor)]


def _expand_keys(agent: Agent) -> list[str]:
    keys: list[str] = []
    if agent.filter is not None:
        keys.extend(sorted(agent.filter.metadata))
    surface = agent.surface_mapping.from_attribute or ""
    if surface.startswith("metadata."):
        key = surface.removeprefix("metadata.")
        if key and key not in keys:
            keys.append(key)
    return keys


def build_phase_one_params(
    agent: Agent, window_start: datetime, window_end: datetime
) -> list[tuple[str, str]]:
    filt: list[dict[str, Any]] = [
        {"type": "boolean", "column": "isRootObservation", "operator": "=", "value": True},
        {
            "type": "datetime",
            "column": "startTime",
            "operator": ">=",
            "value": to_iso(window_start),
        },
        {"type": "datetime", "column": "startTime", "operator": "<", "value": to_iso(window_end)},
    ]
    agent_filter = agent.filter
    if agent_filter is not None and agent_filter.trace_name:
        filt.append(
            {
                "type": "string",
                "column": "traceName",
                "operator": "=",
                "value": agent_filter.trace_name,
            }
        )
    if agent_filter is not None and agent_filter.tags:
        filt.append(
            {
                "type": "arrayOptions",
                "column": "tags",
                "operator": "all of",
                "value": list(agent_filter.tags),
            }
        )
    if agent_filter is not None:
        for key, value in agent_filter.metadata.items():
            filt.append(
                {
                    "type": "stringObject",
                    "column": "metadata",
                    "key": key,
                    "operator": "=",
                    "value": value,
                }
            )
    params = [
        ("fields", "core,basic,trace_context,prompt,metadata"),
        ("isRootObservation", "true"),
        ("fromStartTime", to_iso(window_start)),
        ("toStartTime", to_iso(window_end)),
        ("limit", "1000"),
    ]
    if agent_filter is not None and agent_filter.environment:
        filt.append(
            {
                "type": "stringOptions",
                "column": "environment",
                "operator": "any of",
                "value": [agent_filter.environment],
            }
        )
        params.append(("environment", agent_filter.environment))
    expand = _expand_keys(agent)
    if expand:
        params.append(("expandMetadata", ",".join(expand)))
    params.append(("filter", json.dumps(filt, separators=(",", ":"))))
    return params


def _phase_two_fields(fetch_content: bool) -> str:
    fields = "core,basic,usage,model,prompt"
    if fetch_content:
        return fields + ",io"
    return fields


def build_phase_two_params(
    trace_ids: list[str],
    window_start: datetime,
    window_end: datetime,
    fetch_content: bool,
) -> list[tuple[str, str]]:
    filt = [
        {
            "type": "stringOptions",
            "column": "traceId",
            "operator": "any of",
            "value": trace_ids,
        }
    ]
    return [
        ("fields", _phase_two_fields(fetch_content)),
        ("fromStartTime", to_iso(window_start - timedelta(hours=1))),
        ("toStartTime", to_iso(window_end + timedelta(hours=1))),
        ("limit", "1000"),
        ("filter", json.dumps(filt, separators=(",", ":"))),
    ]


def build_trace_params(
    trace_id: str,
    window_start: datetime,
    window_end: datetime,
    fetch_content: bool,
) -> list[tuple[str, str]]:
    return [
        ("fields", _phase_two_fields(fetch_content)),
        ("fromStartTime", to_iso(window_start - timedelta(hours=1))),
        ("toStartTime", to_iso(window_end + timedelta(hours=1))),
        ("limit", "1000"),
        ("traceId", trace_id),
    ]


def batches(ids: list[str], size: int = BATCH) -> list[list[str]]:
    return [ids[index : index + size] for index in range(0, len(ids), size)]


class LangfuseSync:
    def __init__(
        self,
        connection: Connection,
        client: LangfuseClient,
        event_store: EventStore,
        meta_store: MetaStore,
        settings: Settings,
        keys: HmacKeys,
    ) -> None:
        self.connection = connection
        self._client = client
        self._events = event_store
        self._meta = meta_store
        self._settings = settings
        self._keys = keys
        self.any_of_supported = True

    async def _agents(self) -> list[Agent]:
        agents = [
            agent
            for agent in await self._meta.list_agents(include_deleted=False)
            if agent.source is Source.langfuse
            and agent.langfuse_connection_id == self.connection.id
            and agent.deleted_at is None
        ]
        agents.sort(key=lambda agent: (agent.created_at, agent.id))
        return agents

    async def _paginate(self, params: list[tuple[str, str]]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        cursor: str | None = None
        seen: set[str] = set()
        while True:
            page = await self._client.list_observations(_with_cursor(params, cursor))
            rows.extend(page.data)
            if not page.cursor or page.cursor in seen:
                return rows
            seen.add(page.cursor)
            cursor = page.cursor

    async def _phase_two(
        self,
        trace_ids: list[str],
        window_start: datetime,
        window_end: datetime,
        fetch_content: bool,
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        if self.any_of_supported:
            try:
                for group in batches(trace_ids):
                    params = build_phase_two_params(group, window_start, window_end, fetch_content)
                    rows.extend(await self._paginate(params))
                return rows
            except LangfuseClientError as exc:
                if exc.status_code != 400:
                    raise
                self.any_of_supported = False
                rows = []
        for trace_id in trace_ids:
            params = build_trace_params(trace_id, window_start, window_end, fetch_content)
            rows.extend(await self._paginate(params))
        return rows

    async def _ensure_project(self, now: datetime) -> None:
        if self.connection.config.get("project_id"):
            return
        projects = await self._client.get_projects()
        if not projects:
            return
        project_id = projects[0].get("id")
        if not isinstance(project_id, str) or not project_id:
            return
        config = dict(self.connection.config)
        config["project_id"] = project_id
        self.connection = replace(self.connection, config=config, updated_at=now)
        await self._meta.upsert_connection(self.connection)

    async def run_cycle(self, now: datetime) -> SyncResult:
        label = self.connection.name
        state = await self._meta.get_sync_state(self.connection.id)
        if state is None:
            state = SyncState(
                connection_id=self.connection.id,
                watermark=None,
                last_success_at=None,
                last_error="",
                last_error_at=None,
                lag_seconds=None,
                in_progress=False,
                updated_at=now,
            )
        if state.in_progress and state.updated_at > now - timedelta(minutes=15):
            _LOG.info("langfuse sync skipped", extra={"connection": label, "reason": "in_progress"})
            return SyncResult(skipped=True)
        window_end = now - SAFETY_LAG
        base = state.watermark or (now - INITIAL_BACKFILL)
        window_start = base - LOOKBACK
        if window_start >= window_end:
            _LOG.info(
                "langfuse sync skipped", extra={"connection": label, "reason": "empty_window"}
            )
            return SyncResult(skipped=True)
        await self._meta.upsert_sync_state(replace(state, in_progress=True, updated_at=now))
        try:
            await self._ensure_project(now)
            agents = await self._agents()
            roots: dict[str, tuple[Agent, dict[str, Any]]] = {}
            phase_one_count = 0
            for agent in agents:
                params = build_phase_one_params(agent, window_start, window_end)
                for obs in await self._paginate(params):
                    phase_one_count += 1
                    trace_id = str(obs.get("traceId", ""))
                    if not trace_id:
                        continue
                    if trace_id in roots:
                        OVERLAP.labels(connection=label).inc()
                        continue
                    roots[trace_id] = (agent, obs)
            fetch_content = bool(self.connection.config.get("fetch_content", True))
            phase_two = await self._phase_two(list(roots), window_start, window_end, fetch_content)
            grouped: dict[str, list[dict[str, Any]]] = {}
            for obs in phase_two:
                grouped.setdefault(str(obs.get("traceId", "")), []).append(obs)
            rows: list[SpanRow] = []
            for trace_id, (agent, root_obs) in roots.items():
                by_id: dict[str, dict[str, Any]] = {}
                for obs in grouped.get(trace_id, []):
                    by_id[str(obs.get("id"))] = obs
                root_id = str(root_obs.get("id"))
                if root_id not in by_id:
                    by_id[root_id] = root_obs
                for obs in by_id.values():
                    try:
                        rows.append(
                            to_span_row(
                                obs,
                                root_obs,
                                agent,
                                self.connection,
                                self._keys,
                                self._settings,
                                now,
                            )
                        )
                    except (KeyError, TypeError, ValueError, MalformedSpan):
                        _LOG.warning(
                            "skipped malformed langfuse observation",
                            extra={"connection": self.connection.name},
                        )
            for index in range(0, len(rows), _WRITE_CHUNK):
                await write_batch(self._events, rows[index : index + _WRITE_CHUNK], now)
            lag = int((now - window_end).total_seconds())
            done = now + timedelta(microseconds=1)
            await self._meta.upsert_sync_state(
                SyncState(
                    connection_id=self.connection.id,
                    watermark=window_end,
                    last_success_at=now,
                    last_error="",
                    last_error_at=state.last_error_at,
                    lag_seconds=lag,
                    in_progress=False,
                    updated_at=done,
                )
            )
            FETCHED.labels(connection=label).inc(phase_one_count + len(phase_two))
            LAG.labels(connection=label).set(lag)
            return SyncResult(
                observations=phase_one_count + len(phase_two),
                traces=len(roots),
                spans_written=len(rows),
                window_start=window_start,
                window_end=window_end,
            )
        except Exception as exc:
            failed = now + timedelta(microseconds=1)
            await self._meta.upsert_sync_state(
                SyncState(
                    connection_id=self.connection.id,
                    watermark=state.watermark,
                    last_success_at=state.last_success_at,
                    last_error=f"{type(exc).__name__}: {exc}"[:500],
                    last_error_at=now,
                    lag_seconds=state.lag_seconds,
                    in_progress=False,
                    updated_at=failed,
                )
            )
            raise
