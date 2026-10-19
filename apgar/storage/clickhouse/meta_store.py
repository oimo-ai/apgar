from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel

from apgar.domain.enums import (
    ConnectionStatus,
    ConnectionType,
    JobRequestKind,
    MetricId,
    NotificationChannel,
    NotificationEvent,
    NotificationStatus,
    OutputFormat,
    ReasonCode,
    ReleaseEventType,
    Source,
    VerdictState,
)
from apgar.domain.models import (
    Agent,
    Connection,
    IngestToken,
    JobRequest,
    Notification,
    Release,
    ReleaseEvent,
    SyncState,
    VerdictEvaluation,
)
from apgar.domain.settings import AgentFilter, ReleaseSettings, SurfaceMapping, VerdictSettings
from apgar.security import SecretBox
from apgar.storage.secrets import open_config, seal_config
from apgar.storage.types import ReleaseFilters


def _dump(value: Any) -> str:
    payload = (
        value.model_dump(mode="json", by_alias=True) if isinstance(value, BaseModel) else value
    )
    return json.dumps(payload, separators=(",", ":"), sort_keys=True)


def _load_obj(raw: Any) -> dict[str, Any]:
    if raw is None or raw == "":
        return {}
    data = json.loads(raw) if isinstance(raw, str) else raw
    if not isinstance(data, dict):
        raise TypeError("expected a JSON object")
    return data


def _load_model[T: BaseModel](model: type[T], raw: Any) -> T:
    return model.model_validate(_load_obj(raw))


def _load_filter(raw: Any) -> AgentFilter | None:
    if raw is None or raw == "" or raw == "null":
        return None
    data = json.loads(raw) if isinstance(raw, str) else raw
    if data is None:
        return None
    if not isinstance(data, dict):
        raise TypeError("expected a JSON object")
    return AgentFilter.model_validate(data)


def _dt(value: Any) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"expected datetime, got {type(value).__name__}")
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _opt_dt(value: Any) -> datetime | None:
    if value is None:
        return None
    return _dt(value)


def _opt_int(value: Any) -> int | None:
    if value is None:
        return None
    return int(value)


def _strings(value: Any) -> list[str]:
    if not value:
        return []
    return [str(item) for item in value]


def _metrics(value: Any) -> dict[str, dict[str, Any]]:
    loaded = _load_obj(value)
    parsed: dict[str, dict[str, Any]] = {}
    for key, item in loaded.items():
        if isinstance(item, dict) and str(key) in MetricId._value2member_map_:
            parsed[str(key)] = dict(item)
    return parsed


def _flag(value: bool) -> int:
    return int(value)


_AGENT_COLUMNS = [
    "id",
    "name",
    "source",
    "langfuse_connection_id",
    "filter",
    "environment",
    "surface_mapping",
    "release_settings",
    "metric_settings",
    "verdict_settings",
    "output_format",
    "slack_connection_id",
    "is_demo",
    "created_at",
    "updated_at",
    "deleted_at",
]
_CONNECTION_COLUMNS = [
    "id",
    "name",
    "type",
    "config_encrypted",
    "status",
    "last_checked_at",
    "last_error",
    "created_at",
    "updated_at",
]
_INGEST_TOKEN_COLUMNS = [
    "id",
    "name",
    "token_hash",
    "token_prefix",
    "agent_id",
    "auto_create_agents",
    "created_at",
    "revoked_at",
    "updated_at",
]
_SYNC_COLUMNS = [
    "connection_id",
    "watermark",
    "last_success_at",
    "last_error",
    "last_error_at",
    "lag_seconds",
    "in_progress",
    "updated_at",
]
_RELEASE_COLUMNS = [
    "agent_id",
    "release",
    "first_seen",
    "state",
    "reason",
    "final",
    "final_at",
    "selected_baseline_release",
    "selected_baseline_mode",
    "baseline_unverified",
    "verdict_summary",
    "verdict_updated_at",
    "last_seen",
    "turn_count",
    "updated_at",
]
_RELEASE_EVENT_COLUMNS = ["agent_id", "release", "ts", "type", "payload", "actor"]
_EVALUATION_COLUMNS = [
    "agent_id",
    "release",
    "evaluated_at",
    "manual",
    "seed",
    "baseline_release",
    "baseline_mode",
    "baseline_unverified",
    "window_start",
    "window_end",
    "n_candidate_turns",
    "n_baseline_turns",
    "n_candidate_sessions",
    "n_baseline_sessions",
    "n_excluded_mixed",
    "n_excluded_untagged",
    "n_excluded_late",
    "state",
    "reason",
    "final",
    "metrics",
    "slices",
    "duration_ms",
]
_NOTIFICATION_COLUMNS = [
    "id",
    "agent_id",
    "release",
    "event",
    "idempotency_key",
    "channel",
    "connection_id",
    "status",
    "attempts",
    "next_attempt_at",
    "last_error",
    "payload",
    "created_at",
    "updated_at",
]
_JOB_COLUMNS = [
    "id",
    "agent_id",
    "release",
    "kind",
    "payload",
    "requested_at",
    "processed_at",
    "updated_at",
]


def _agent_values(agent: Agent, *, is_deleted: int) -> list[Any]:
    return [
        agent.id,
        agent.name,
        agent.source.value,
        agent.langfuse_connection_id,
        "null" if agent.filter is None else _dump(agent.filter),
        agent.environment,
        _dump(agent.surface_mapping),
        _dump(agent.release_settings),
        _dump(agent.metric_settings),
        _dump(agent.verdict_settings),
        agent.output_format.value,
        agent.slack_connection_id,
        _flag(agent.is_demo),
        agent.created_at,
        agent.updated_at,
        agent.deleted_at,
        is_deleted,
    ]


def _agent_from(row: dict[str, Any]) -> Agent:
    return Agent(
        id=str(row["id"]),
        name=str(row["name"]),
        source=Source(str(row["source"])),
        langfuse_connection_id=str(row["langfuse_connection_id"]),
        filter=_load_filter(row["filter"]),
        environment=str(row["environment"]),
        surface_mapping=_load_model(SurfaceMapping, row["surface_mapping"]),
        release_settings=_load_model(ReleaseSettings, row["release_settings"]),
        metric_settings=_metrics(row["metric_settings"]),
        verdict_settings=VerdictSettings.from_stored(_load_obj(row["verdict_settings"])),
        output_format=OutputFormat(str(row["output_format"])),
        slack_connection_id=str(row["slack_connection_id"]),
        is_demo=bool(row["is_demo"]),
        created_at=_dt(row["created_at"]),
        updated_at=_dt(row["updated_at"]),
        deleted_at=_opt_dt(row["deleted_at"]),
    )


def _connection_values(connection: Connection, *, is_deleted: int, sealed: str) -> list[Any]:
    return [
        connection.id,
        connection.name,
        connection.type.value,
        sealed,
        connection.status.value,
        connection.last_checked_at,
        connection.last_error,
        connection.created_at,
        connection.updated_at,
        is_deleted,
    ]


def _connection_from(row: dict[str, Any], box: SecretBox | None) -> Connection:
    raw = row["config_encrypted"]
    if isinstance(raw, bytes):
        encoded = raw.decode()
    elif raw is None:
        encoded = ""
    else:
        encoded = str(raw)
    return Connection(
        id=str(row["id"]),
        name=str(row["name"]),
        type=ConnectionType(str(row["type"])),
        config=open_config(encoded, box),
        status=ConnectionStatus(str(row["status"])),
        last_checked_at=_opt_dt(row["last_checked_at"]),
        last_error=str(row["last_error"]),
        created_at=_dt(row["created_at"]),
        updated_at=_dt(row["updated_at"]),
    )


def _ingest_values(token: IngestToken, *, is_deleted: int) -> list[Any]:
    return [
        token.id,
        token.name,
        token.token_hash,
        token.token_prefix,
        token.agent_id,
        _flag(token.auto_create_agents),
        token.created_at,
        token.revoked_at,
        token.updated_at,
        is_deleted,
    ]


def _ingest_from(row: dict[str, Any]) -> IngestToken:
    return IngestToken(
        id=str(row["id"]),
        name=str(row["name"]),
        token_hash=str(row["token_hash"]),
        token_prefix=str(row["token_prefix"]),
        agent_id=str(row["agent_id"]),
        auto_create_agents=bool(row["auto_create_agents"]),
        created_at=_dt(row["created_at"]),
        revoked_at=_opt_dt(row["revoked_at"]),
        updated_at=_dt(row["updated_at"]),
    )


def _sync_values(state: SyncState, *, is_deleted: int) -> list[Any]:
    return [
        state.connection_id,
        state.watermark,
        state.last_success_at,
        state.last_error,
        state.last_error_at,
        state.lag_seconds,
        _flag(state.in_progress),
        state.updated_at,
        is_deleted,
    ]


def _sync_from(row: dict[str, Any]) -> SyncState:
    return SyncState(
        connection_id=str(row["connection_id"]),
        watermark=_opt_dt(row["watermark"]),
        last_success_at=_opt_dt(row["last_success_at"]),
        last_error=str(row["last_error"]),
        last_error_at=_opt_dt(row["last_error_at"]),
        lag_seconds=_opt_int(row["lag_seconds"]),
        in_progress=bool(row["in_progress"]),
        updated_at=_dt(row["updated_at"]),
    )


def _release_values(release: Release) -> list[Any]:
    return [
        release.agent_id,
        release.release,
        release.first_seen,
        release.state.value,
        release.reason.value,
        _flag(release.final),
        release.final_at,
        release.selected_baseline_release,
        release.selected_baseline_mode,
        _flag(release.baseline_unverified),
        _dump(release.verdict_summary),
        release.verdict_updated_at,
        release.last_seen,
        release.turn_count,
        release.updated_at,
    ]


def _release_from(row: dict[str, Any]) -> Release:
    return Release(
        agent_id=str(row["agent_id"]),
        release=str(row["release"]),
        first_seen=_dt(row["first_seen"]),
        state=VerdictState(str(row["state"])),
        reason=ReasonCode(str(row["reason"])),
        final=bool(row["final"]),
        final_at=_opt_dt(row["final_at"]),
        selected_baseline_release=str(row["selected_baseline_release"]),
        selected_baseline_mode=str(row["selected_baseline_mode"]),
        baseline_unverified=bool(row["baseline_unverified"]),
        verdict_summary=_load_obj(row["verdict_summary"]),
        verdict_updated_at=_opt_dt(row["verdict_updated_at"]),
        last_seen=_opt_dt(row["last_seen"]),
        turn_count=int(row["turn_count"]),
        updated_at=_dt(row["updated_at"]),
    )


def _event_values(event: ReleaseEvent) -> list[Any]:
    return [
        event.agent_id,
        event.release,
        event.ts,
        event.type.value,
        _dump(event.payload),
        event.actor,
    ]


def _event_from(row: dict[str, Any]) -> ReleaseEvent:
    return ReleaseEvent(
        agent_id=str(row["agent_id"]),
        release=str(row["release"]),
        ts=_dt(row["ts"]),
        type=ReleaseEventType(str(row["type"])),
        payload=_load_obj(row["payload"]),
        actor=str(row["actor"]),
    )


def _evaluation_values(evaluation: VerdictEvaluation) -> list[Any]:
    return [
        evaluation.agent_id,
        evaluation.release,
        evaluation.evaluated_at,
        _flag(evaluation.manual),
        evaluation.seed,
        evaluation.baseline_release,
        evaluation.baseline_mode,
        _flag(evaluation.baseline_unverified),
        evaluation.window_start,
        evaluation.window_end,
        evaluation.n_candidate_turns,
        evaluation.n_baseline_turns,
        evaluation.n_candidate_sessions,
        evaluation.n_baseline_sessions,
        evaluation.n_excluded_mixed,
        evaluation.n_excluded_untagged,
        evaluation.n_excluded_late,
        evaluation.state.value,
        evaluation.reason.value,
        _flag(evaluation.final),
        _dump(evaluation.metrics),
        _dump(evaluation.slices),
        evaluation.duration_ms,
    ]


def _evaluation_from(row: dict[str, Any]) -> VerdictEvaluation:
    return VerdictEvaluation(
        agent_id=str(row["agent_id"]),
        release=str(row["release"]),
        evaluated_at=_dt(row["evaluated_at"]),
        manual=bool(row["manual"]),
        seed=str(row["seed"]),
        baseline_release=str(row["baseline_release"]),
        baseline_mode=str(row["baseline_mode"]),
        baseline_unverified=bool(row["baseline_unverified"]),
        window_start=_opt_dt(row["window_start"]),
        window_end=_opt_dt(row["window_end"]),
        n_candidate_turns=int(row["n_candidate_turns"]),
        n_baseline_turns=int(row["n_baseline_turns"]),
        n_candidate_sessions=int(row["n_candidate_sessions"]),
        n_baseline_sessions=int(row["n_baseline_sessions"]),
        n_excluded_mixed=int(row["n_excluded_mixed"]),
        n_excluded_untagged=int(row["n_excluded_untagged"]),
        n_excluded_late=int(row["n_excluded_late"]),
        state=VerdictState(str(row["state"])),
        reason=ReasonCode(str(row["reason"])),
        final=bool(row["final"]),
        metrics=_load_obj(row["metrics"]),
        slices=_load_obj(row["slices"]),
        duration_ms=int(row["duration_ms"]),
    )


def _notification_values(notification: Notification) -> list[Any]:
    return [
        notification.id,
        notification.agent_id,
        notification.release,
        notification.event.value,
        notification.idempotency_key,
        notification.channel.value,
        notification.connection_id,
        notification.status.value,
        notification.attempts,
        notification.next_attempt_at,
        notification.last_error,
        _dump(notification.payload),
        notification.created_at,
        notification.updated_at,
    ]


def _notification_from(row: dict[str, Any]) -> Notification:
    return Notification(
        id=str(row["id"]),
        agent_id=str(row["agent_id"]),
        release=str(row["release"]),
        event=NotificationEvent(str(row["event"])),
        idempotency_key=str(row["idempotency_key"]),
        channel=NotificationChannel(str(row["channel"])),
        connection_id=str(row["connection_id"]),
        status=NotificationStatus(str(row["status"])),
        attempts=int(row["attempts"]),
        next_attempt_at=_dt(row["next_attempt_at"]),
        last_error=str(row["last_error"]),
        payload=_load_obj(row["payload"]),
        created_at=_dt(row["created_at"]),
        updated_at=_dt(row["updated_at"]),
    )


def _job_values(job: JobRequest) -> list[Any]:
    return [
        job.id,
        job.agent_id,
        job.release,
        job.kind.value,
        _dump(job.payload),
        job.requested_at,
        job.processed_at,
        job.updated_at,
    ]


def _job_from(row: dict[str, Any]) -> JobRequest:
    return JobRequest(
        id=str(row["id"]),
        agent_id=str(row["agent_id"]),
        release=str(row["release"]),
        kind=JobRequestKind(str(row["kind"])),
        payload=_load_obj(row["payload"]),
        requested_at=_dt(row["requested_at"]),
        processed_at=_opt_dt(row["processed_at"]),
        updated_at=_dt(row["updated_at"]),
    )


class ClickHouseMetaStore:
    def __init__(self, client: Any, box: SecretBox | None = None) -> None:
        self.client = client
        self._box = box

    async def _scalar(self, sql: str, parameters: dict[str, Any] | None = None) -> Any:
        result: Any = await self.client.query(sql, parameters=parameters or {})
        if not result.result_rows:
            return None
        return result.result_rows[0][0]

    async def _select(
        self,
        table: str,
        columns: Sequence[str],
        where: str,
        parameters: dict[str, Any],
        *,
        final: bool = True,
        order: str = "",
        limit: int | None = None,
        offset: int | None = None,
    ) -> list[dict[str, Any]]:
        cols = ", ".join(f"`{column}`" for column in columns)
        final_sql = " FINAL" if final else ""
        sql = f"SELECT {cols} FROM `{table}`{final_sql} WHERE {where}"
        params = dict(parameters)
        if order:
            sql = f"{sql} ORDER BY {order}"
        if limit is not None:
            sql = f"{sql} LIMIT {{limit:UInt32}}"
            params["limit"] = limit
            if offset is not None:
                sql = f"{sql} OFFSET {{offset:UInt32}}"
                params["offset"] = offset
        result: Any = await self.client.query(sql, parameters=params)
        names = [str(name) for name in result.column_names]
        return [
            {names[index]: raw[index] for index in range(len(names))} for raw in result.result_rows
        ]

    async def _insert(self, table: str, columns: Sequence[str], values: Sequence[Any]) -> None:
        await self.client.insert(table, [list(values)], column_names=list(columns))

    async def schema_version(self) -> int:
        exists = await self._scalar("EXISTS TABLE schema_migrations")
        if not int(exists or 0):
            return 0
        value = await self._scalar("SELECT max(version) FROM schema_migrations")
        if value is None:
            return 0
        return int(value)

    async def list_agents(
        self, include_demo: bool = True, include_deleted: bool = False
    ) -> list[Agent]:
        rows = await self._select(
            "agents",
            _AGENT_COLUMNS,
            "is_deleted = 0 AND ({include_deleted:UInt8} = 1 OR deleted_at IS NULL) "
            "AND ({include_demo:UInt8} = 1 OR is_demo = 0)",
            {"include_deleted": _flag(include_deleted), "include_demo": _flag(include_demo)},
            order="name",
        )
        return [_agent_from(row) for row in rows]

    async def get_agent(self, agent_id: str, include_deleted: bool = False) -> Agent | None:
        where = "is_deleted = 0 AND id = {agent_id:String}"
        if not include_deleted:
            where = f"{where} AND deleted_at IS NULL"
        rows = await self._select("agents", _AGENT_COLUMNS, where, {"agent_id": agent_id})
        if not rows:
            return None
        return _agent_from(rows[0])

    async def get_agent_by_name(self, name: str) -> Agent | None:
        rows = await self._select(
            "agents",
            _AGENT_COLUMNS,
            "is_deleted = 0 AND deleted_at IS NULL AND name = {name:String}",
            {"name": name},
            limit=1,
        )
        if not rows:
            return None
        return _agent_from(rows[0])

    async def upsert_agent(self, agent: Agent) -> None:
        await self._insert(
            "agents", [*_AGENT_COLUMNS, "is_deleted"], _agent_values(agent, is_deleted=0)
        )

    async def delete_agent(self, agent_id: str, now: datetime) -> None:
        current = await self.get_agent(agent_id, include_deleted=True)
        if current is None:
            return
        updated = replace(current, deleted_at=now, updated_at=now)
        await self._insert(
            "agents", [*_AGENT_COLUMNS, "is_deleted"], _agent_values(updated, is_deleted=0)
        )

    async def finalize_agent_deletion(self, agent_id: str, now: datetime) -> None:
        current = await self.get_agent(agent_id, include_deleted=True)
        if current is None:
            return
        updated = replace(current, updated_at=now)
        await self._insert(
            "agents", [*_AGENT_COLUMNS, "is_deleted"], _agent_values(updated, is_deleted=1)
        )

    async def list_connections(self) -> list[Connection]:
        rows = await self._select(
            "connections",
            _CONNECTION_COLUMNS,
            "is_deleted = 0",
            {},
            order="name",
        )
        return [_connection_from(row, self._box) for row in rows]

    async def get_connection(self, connection_id: str) -> Connection | None:
        rows = await self._select(
            "connections",
            _CONNECTION_COLUMNS,
            "is_deleted = 0 AND id = {connection_id:String}",
            {"connection_id": connection_id},
            limit=1,
        )
        if not rows:
            return None
        return _connection_from(rows[0], self._box)

    async def connection_ciphertext(self, connection_id: str) -> str | None:
        rows = await self._select(
            "connections",
            ["config_encrypted"],
            "is_deleted = 0 AND id = {connection_id:String}",
            {"connection_id": connection_id},
            limit=1,
        )
        if not rows:
            return None
        raw = rows[0]["config_encrypted"]
        if isinstance(raw, bytes):
            return raw.decode()
        if raw is None:
            return None
        return str(raw)

    async def upsert_connection(self, connection: Connection) -> None:
        await self._insert(
            "connections",
            [*_CONNECTION_COLUMNS, "is_deleted"],
            _connection_values(
                connection, is_deleted=0, sealed=seal_config(connection.config, self._box)
            ),
        )

    async def delete_connection(self, connection_id: str, now: datetime) -> None:
        current = await self.get_connection(connection_id)
        if current is None:
            return
        updated = replace(current, updated_at=now)
        await self._insert(
            "connections",
            [*_CONNECTION_COLUMNS, "is_deleted"],
            _connection_values(
                updated, is_deleted=1, sealed=seal_config(updated.config, self._box)
            ),
        )

    async def list_ingest_tokens(self) -> list[IngestToken]:
        rows = await self._select(
            "ingest_tokens",
            _INGEST_TOKEN_COLUMNS,
            "is_deleted = 0",
            {},
            order="created_at",
        )
        return [_ingest_from(row) for row in rows]

    async def get_ingest_token_by_hash(self, token_hash: str) -> IngestToken | None:
        rows = await self._select(
            "ingest_tokens",
            _INGEST_TOKEN_COLUMNS,
            "is_deleted = 0 AND token_hash = {token_hash:String}",
            {"token_hash": token_hash},
            limit=1,
        )
        if not rows:
            return None
        return _ingest_from(rows[0])

    async def upsert_ingest_token(self, token: IngestToken) -> None:
        await self._insert(
            "ingest_tokens",
            [*_INGEST_TOKEN_COLUMNS, "is_deleted"],
            _ingest_values(token, is_deleted=0),
        )

    async def get_setting(self, key: str) -> str | None:
        rows = await self._select(
            "settings",
            ["key", "value"],
            "is_deleted = 0 AND `key` = {setting_key:String}",
            {"setting_key": key},
            limit=1,
        )
        if not rows:
            return None
        return str(rows[0]["value"])

    async def set_setting(self, key: str, value: str, now: datetime) -> None:
        await self._insert(
            "settings",
            ["key", "value", "updated_at", "is_deleted"],
            [key, value, now, 0],
        )

    async def delete_setting(self, key: str, now: datetime) -> None:
        current = await self.get_setting(key)
        await self._insert(
            "settings",
            ["key", "value", "updated_at", "is_deleted"],
            [key, "" if current is None else current, now, 1],
        )

    async def list_settings(self, prefix: str) -> dict[str, str]:
        rows = await self._select(
            "settings",
            ["key", "value"],
            "is_deleted = 0 AND startsWith(`key`, {prefix:String})",
            {"prefix": prefix},
            order="`key`",
        )
        return {str(row["key"]): str(row["value"]) for row in rows}

    async def get_sync_state(self, connection_id: str) -> SyncState | None:
        rows = await self._select(
            "sync_state",
            _SYNC_COLUMNS,
            "is_deleted = 0 AND connection_id = {connection_id:String}",
            {"connection_id": connection_id},
            limit=1,
        )
        if not rows:
            return None
        return _sync_from(rows[0])

    async def upsert_sync_state(self, state: SyncState) -> None:
        await self._insert(
            "sync_state", [*_SYNC_COLUMNS, "is_deleted"], _sync_values(state, is_deleted=0)
        )

    async def get_release(self, agent_id: str, release: str) -> Release | None:
        rows = await self._select(
            "releases",
            _RELEASE_COLUMNS,
            "agent_id = {agent_id:String} AND release = {release:String}",
            {"agent_id": agent_id, "release": release},
            limit=1,
        )
        if not rows:
            return None
        return _release_from(rows[0])

    async def list_releases(self, filters: ReleaseFilters) -> list[Release]:
        clauses = ["1"]
        params: dict[str, Any] = {}
        if filters.agent_id is not None:
            clauses.append("agent_id = {agent_id:String}")
            params["agent_id"] = filters.agent_id
        if filters.final is not None:
            clauses.append("`final` = {is_final:UInt8}")
            params["is_final"] = _flag(filters.final)
        rows = await self._select(
            "releases",
            _RELEASE_COLUMNS,
            " AND ".join(clauses),
            params,
            order="agent_id, release",
            limit=filters.limit,
            offset=filters.offset,
        )
        return [_release_from(row) for row in rows]

    async def upsert_release(self, release: Release) -> None:
        await self._insert("releases", _RELEASE_COLUMNS, _release_values(release))

    async def append_release_event(self, event: ReleaseEvent) -> None:
        await self._insert("release_events", _RELEASE_EVENT_COLUMNS, _event_values(event))

    async def release_events(self, agent_id: str, release: str) -> list[ReleaseEvent]:
        rows = await self._select(
            "release_events",
            _RELEASE_EVENT_COLUMNS,
            "agent_id = {agent_id:String} AND release = {release:String}",
            {"agent_id": agent_id, "release": release},
            final=False,
            order="ts, `type`",
        )
        return [_event_from(row) for row in rows]

    async def append_evaluation(self, evaluation: VerdictEvaluation) -> None:
        await self._insert(
            "verdict_evaluations", _EVALUATION_COLUMNS, _evaluation_values(evaluation)
        )

    async def list_evaluations(
        self, agent_id: str, release: str, limit: int
    ) -> list[VerdictEvaluation]:
        rows = await self._select(
            "verdict_evaluations",
            _EVALUATION_COLUMNS,
            "agent_id = {agent_id:String} AND release = {release:String}",
            {"agent_id": agent_id, "release": release},
            final=False,
            order="evaluated_at DESC",
            limit=limit,
        )
        return [_evaluation_from(row) for row in rows]

    async def upsert_notification(self, notification: Notification) -> None:
        await self._insert(
            "notifications", _NOTIFICATION_COLUMNS, _notification_values(notification)
        )

    async def get_notification(
        self, idempotency_key: str, channel: NotificationChannel
    ) -> Notification | None:
        rows = await self._select(
            "notifications",
            _NOTIFICATION_COLUMNS,
            "idempotency_key = {idempotency_key:String} AND channel = {channel:String}",
            {"idempotency_key": idempotency_key, "channel": channel.value},
            limit=1,
        )
        if not rows:
            return None
        return _notification_from(rows[0])

    async def due_notifications(
        self,
        now: datetime,
        limit: int,
    ) -> list[Notification]:
        where = "status = {status:String} AND next_attempt_at <= {now:DateTime64(3)}"
        params: dict[str, Any] = {"status": NotificationStatus.pending.value, "now": now}
        rows = await self._select(
            "notifications",
            _NOTIFICATION_COLUMNS,
            where,
            params,
            order="next_attempt_at, idempotency_key",
            limit=limit,
        )
        return [_notification_from(row) for row in rows]

    async def list_notifications(
        self, status: NotificationStatus | None, limit: int
    ) -> list[Notification]:
        clauses = ["1"]
        params: dict[str, Any] = {}
        if status is not None:
            clauses.append("status = {status:String}")
            params["status"] = status.value
        rows = await self._select(
            "notifications",
            _NOTIFICATION_COLUMNS,
            " AND ".join(clauses),
            params,
            order="created_at DESC",
            limit=limit,
        )
        return [_notification_from(row) for row in rows]

    async def enqueue_job(self, job: JobRequest) -> None:
        await self._insert("job_requests", _JOB_COLUMNS, _job_values(job))

    async def pending_jobs(self, limit: int) -> list[JobRequest]:
        rows = await self._select(
            "job_requests",
            _JOB_COLUMNS,
            "processed_at IS NULL",
            {},
            order="requested_at, id",
            limit=limit,
        )
        return [_job_from(row) for row in rows]

    async def complete_job(self, job: JobRequest, now: datetime) -> None:
        updated = replace(job, processed_at=now, updated_at=now)
        await self._insert("job_requests", _JOB_COLUMNS, _job_values(updated))
