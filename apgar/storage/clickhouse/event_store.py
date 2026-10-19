from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any, NoReturn

from apgar.domain.enums import SpanKind, SpanStatus
from apgar.domain.models import (
    SpanRow,
    ToolCallRow,
    TraceStateRow,
    TurnKey,
    TurnRow,
)
from apgar.domain.retention import SESSION_LOOKBACK_DAYS
from apgar.storage.arm import ScopedTurn, ToolFact, assemble_arm
from apgar.storage.clickhouse.client import INSERT_SETTINGS, load_sql
from apgar.storage.types import (
    AgentActivity,
    ArmData,
    ArmQuery,
    ReleaseActivity,
)

_SPAN_COLUMNS = [
    "source_id",
    "trace_id",
    "span_id",
    "parent_span_id",
    "kind",
    "name",
    "start_ts",
    "end_ts",
    "status",
    "error_type",
    "agent_hint",
    "attributes",
    "request_model",
    "response_model",
    "input_tokens",
    "output_tokens",
    "cost_usd",
    "tool_name",
    "tool_call_id",
    "args_hash",
    "output_chars",
    "output_json_valid",
    "late",
    "ingested_at",
]
_TRACE_COLUMNS = [
    "source_id",
    "trace_id",
    "first_span_at",
    "last_span_at",
    "span_count",
    "has_root",
    "agent_id",
    "root_span_id",
    "release",
    "start_ts",
    "assembled_at",
    "assembled_version",
    "content_hash",
    "updated_at",
]
_TURN_COLUMNS = [
    "agent_id",
    "release",
    "start_ts",
    "turn_id",
    "trace_id",
    "root_span_id",
    "source_id",
    "environment",
    "prompt_version",
    "session_id",
    "session_inferred",
    "surface",
    "end_ts",
    "latency_ms",
    "llm_calls",
    "llm_errors",
    "tool_calls",
    "tool_errors",
    "tool_retries",
    "loop_flag",
    "zero_tool_flag",
    "input_tokens",
    "output_tokens",
    "output_chars",
    "cost_usd",
    "primary_response_model",
    "response_models",
    "format_ok",
    "late",
    "partial",
    "source",
    "ingested_at",
    "version",
]
_TOOL_COLUMNS = [
    "agent_id",
    "release",
    "turn_start_ts",
    "turn_id",
    "tool_call_id",
    "session_id",
    "tool_name",
    "call_start_ts",
    "duration_ms",
    "status",
    "error_type",
    "args_hash",
    "is_retry",
    "surface",
    "version",
]
_PURGE_TABLES = (
    "turns",
    "tool_calls",
    "releases",
    "release_events",
    "verdict_evaluations",
    "notifications",
    "job_requests",
)


def _scoped_from(row: dict[str, Any]) -> ScopedTurn:
    return ScopedTurn(
        turn_id=str(row["turn_id"]),
        trace_id=str(row["trace_id"]),
        session_id=str(row["session_id"]),
        start_ts=_dt(row["start_ts"]),
        end_ts=_dt(row["end_ts"]),
        surface=str(row["surface"]),
        depth_bucket=str(row["depth_bucket"]),
        response_model=str(row["primary_response_model"]),
        prompt_version=str(row["prompt_version"]),
        turn_index=int(row["turn_index"]),
        mixed_session=bool(int(row["mixed_session"])),
        session_inferred=bool(int(row["session_inferred"])),
        session_closed=bool(int(row["session_closed"])),
        session_first_start=_dt(row["session_first_start"]),
        llm_error=int(row["llm_errors"]) > 0,
        tool_call_count=int(row["tool_calls"]),
        tool_error_count=int(row["tool_errors"]),
        zero_tool=bool(int(row["zero_tool_flag"])),
        loop_flag=_opt_bool(row["loop_flag"]),
        format_ok=_opt_bool(row["format_ok"]),
        output_tokens=_opt_int(row["output_tokens"]),
        output_chars=_opt_int(row["output_chars"]),
        latency_ms=int(row["latency_ms"]),
        cost_usd=None if row["cost_usd"] is None else float(row["cost_usd"]),
        is_late=bool(int(row["late"])),
    )


def _tool_fact(row: dict[str, Any]) -> ToolFact:
    return ToolFact(
        turn_id=str(row["turn_id"]),
        session_id=str(row["session_id"]),
        tool_name=str(row["tool_name"]),
        is_error=str(row["status"]) == "error",
        has_args_hash=str(row["args_hash"]) != "",
        is_retry=_opt_bool(row["is_retry"]),
    )


def _later(milestone: str) -> NoReturn:
    raise NotImplementedError(f"implemented in {milestone}")


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


def _flag(value: bool) -> int:
    return int(value)


def _opt_flag(value: bool | None) -> int | None:
    if value is None:
        return None
    return int(value)


def _opt_int(value: Any) -> int | None:
    if value is None:
        return None
    return int(value)


def _opt_bool(value: Any) -> bool | None:
    if value is None:
        return None
    return bool(int(value))


def _strings(value: Any) -> list[str]:
    if not value:
        return []
    return [str(item) for item in value]


def _attrs(value: Any) -> dict[str, str]:
    if not value:
        return {}
    return {str(key): str(item) for key, item in dict(value).items()}


class ClickHouseEventStore:
    def __init__(self, client: Any) -> None:
        self.client = client

    async def _query(
        self, sql: str, parameters: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        result: Any = await self.client.query(sql, parameters=parameters or {})
        names = [str(name) for name in result.column_names]
        return [
            {names[index]: raw[index] for index in range(len(names))} for raw in result.result_rows
        ]

    async def _insert(
        self,
        table: str,
        columns: Sequence[str],
        rows: Sequence[Sequence[Any]],
    ) -> None:
        if not rows:
            return
        await self.client.insert(
            table,
            [list(row) for row in rows],
            column_names=list(columns),
            settings=INSERT_SETTINGS,
        )

    async def insert_spans(self, rows: Sequence[SpanRow]) -> None:
        await self._insert(
            "spans",
            _SPAN_COLUMNS,
            [
                [
                    row.source_id,
                    row.trace_id,
                    row.span_id,
                    row.parent_span_id,
                    row.kind.value,
                    row.name,
                    row.start_ts,
                    row.end_ts,
                    row.status.value,
                    row.error_type,
                    row.agent_hint,
                    dict(row.attributes),
                    row.request_model,
                    row.response_model,
                    row.input_tokens,
                    row.output_tokens,
                    row.cost_usd,
                    row.tool_name,
                    row.tool_call_id,
                    row.args_hash,
                    row.output_chars,
                    _opt_flag(row.output_json_valid),
                    _flag(row.late),
                    row.ingested_at,
                ]
                for row in rows
            ],
        )

    async def read_trace_state(
        self, keys: Sequence[tuple[str, str]]
    ) -> dict[tuple[str, str], TraceStateRow]:
        if not keys:
            return {}
        rows = await self._query(
            "SELECT * FROM trace_state FINAL "
            "WHERE (source_id, trace_id) IN {keys:Array(Tuple(String, String))}",
            {"keys": [tuple(key) for key in keys]},
        )
        parsed = [_trace_from(row) for row in rows]
        return {(row.source_id, row.trace_id): row for row in parsed}

    async def upsert_trace_state(self, rows: Sequence[TraceStateRow]) -> None:
        await self._insert(
            "trace_state",
            _TRACE_COLUMNS,
            [
                [
                    row.source_id,
                    row.trace_id,
                    row.first_span_at,
                    row.last_span_at,
                    row.span_count,
                    _flag(row.has_root),
                    row.agent_id,
                    row.root_span_id,
                    row.release,
                    row.start_ts,
                    row.assembled_at,
                    row.assembled_version,
                    row.content_hash,
                    row.updated_at,
                ]
                for row in rows
            ],
        )

    async def traces_due_for_assembly(
        self,
        now: datetime,
        quiet_seconds: int,
        max_age_seconds: int,
        limit: int,
    ) -> list[TraceStateRow]:
        rows = await self._query(
            load_sql("traces_due"),
            {"now": now, "quiet": quiet_seconds, "max_age": max_age_seconds, "limit": limit},
        )
        return [_trace_from(row) for row in rows]

    async def spans_of_trace(self, source_id: str, trace_id: str) -> list[SpanRow]:
        grouped = await self.spans_of_traces([(source_id, trace_id)])
        return grouped.get((source_id, trace_id), [])

    async def spans_of_traces(
        self, keys: Sequence[tuple[str, str]]
    ) -> dict[tuple[str, str], list[SpanRow]]:
        grouped: dict[tuple[str, str], list[SpanRow]] = {key: [] for key in keys}
        if not keys:
            return grouped
        rows = await self._query(
            "SELECT * FROM spans FINAL "
            "WHERE (source_id, trace_id) IN {keys:Array(Tuple(String, String))}",
            {"keys": list(keys)},
        )
        for row in rows:
            span = _span_from(row)
            grouped.setdefault((span.source_id, span.trace_id), []).append(span)
        for spans in grouped.values():
            spans.sort(key=lambda span: (span.start_ts, span.span_id))
        return grouped

    async def find_turn_by_trace(self, trace_id: str) -> TurnKey | None:
        rows = await self._query(
            "SELECT agent_id, release, start_ts, turn_id, max(version) AS version FROM turns "
            "WHERE trace_id = {t:String} "
            "GROUP BY agent_id, release, start_ts, turn_id "
            "ORDER BY version DESC LIMIT 1",
            {"t": trace_id},
        )
        if not rows:
            return None
        row = rows[0]
        return TurnKey(
            agent_id=str(row["agent_id"]),
            release=str(row["release"]),
            start_ts=_dt(row["start_ts"]),
            turn_id=str(row["turn_id"]),
            version=int(row["version"]),
        )

    async def find_turns_by_traces(self, trace_ids: Sequence[str]) -> dict[str, TurnKey | None]:
        found: dict[str, TurnKey | None] = {trace_id: None for trace_id in trace_ids}
        if not trace_ids:
            return found
        rows = await self._query(
            "SELECT trace_id, agent_id, release, start_ts, turn_id, max(version) AS version "
            "FROM turns WHERE trace_id IN {ids:Array(String)} "
            "GROUP BY trace_id, agent_id, release, start_ts, turn_id",
            {"ids": list(trace_ids)},
        )
        for row in rows:
            trace_id = str(row["trace_id"])
            key = TurnKey(
                agent_id=str(row["agent_id"]),
                release=str(row["release"]),
                start_ts=_dt(row["start_ts"]),
                turn_id=str(row["turn_id"]),
                version=int(row["version"]),
            )
            current = found.get(trace_id)
            if current is None or key.version > current.version:
                found[trace_id] = key
        return found

    async def upsert_turns(self, rows: Sequence[TurnRow]) -> None:
        await self._insert("turns", _TURN_COLUMNS, [_turn_values(row) for row in rows])

    async def insert_tool_calls(self, rows: Sequence[ToolCallRow]) -> None:
        await self._insert(
            "tool_calls",
            _TOOL_COLUMNS,
            [
                [
                    row.agent_id,
                    row.release,
                    row.turn_start_ts,
                    row.turn_id,
                    row.tool_call_id,
                    row.session_id,
                    row.tool_name,
                    row.call_start_ts,
                    row.duration_ms,
                    row.status.value,
                    row.error_type,
                    row.args_hash,
                    _opt_flag(row.is_retry),
                    row.surface,
                    row.version,
                ]
                for row in rows
            ],
        )

    async def load_arm(self, query: ArmQuery) -> ArmData:
        scope = (
            "release = {release:String} AND start_ts >= {ws:DateTime64(3)} "
            "AND start_ts < {we:DateTime64(3)}"
        )
        env_sql = ""
        if query.environment:
            scope += " AND environment = {env:String}"
            env_sql = " AND environment = {env:String}"
        sql = load_sql("session_fields").replace("__SCOPE__", scope)
        sql = f"{sql}\n{load_sql('load_arm').replace('__ENV__', env_sql)}"
        minimum = query.session_min_first_start or datetime(1970, 1, 1, tzinfo=UTC)
        parameters = {
            "agent_id": query.agent_id,
            "release": query.release,
            "ws": query.window_start,
            "we": query.window_end,
            "now": query.now,
            "lookback_start": query.window_start - timedelta(days=SESSION_LOOKBACK_DAYS),
            "min_first": minimum,
            "env": query.environment,
        }
        rows = await self._query(sql, parameters)
        scoped = [_scoped_from(row) for row in rows]
        turn_ids = {turn.turn_id for turn in scoped if not turn.is_late}
        tool_rows = await self._query(
            "SELECT turn_id, session_id, tool_name, status, args_hash, is_retry "
            "FROM tool_calls FINAL WHERE agent_id = {a:String} AND release = {r:String} "
            "AND turn_start_ts >= {ws:DateTime64(3)} AND turn_start_ts < {we:DateTime64(3)}",
            {
                "a": query.agent_id,
                "r": query.release,
                "ws": query.window_start,
                "we": query.window_end,
            },
        )
        facts = [_tool_fact(row) for row in tool_rows if str(row["turn_id"]) in turn_ids]
        untagged = 0
        if query.count_untagged:
            counted = await self._query(
                "SELECT count() AS n FROM turns FINAL WHERE agent_id = {a:String} "
                "AND release = 'untagged' AND start_ts >= {ws:DateTime64(3)} "
                "AND start_ts < {we:DateTime64(3)}",
                {"a": query.agent_id, "ws": query.window_start, "we": query.window_end},
            )
            untagged = int(counted[0]["n"]) if counted else 0
        return assemble_arm(scoped, facts, query, untagged)

    async def dirty_agents(self, since: datetime, now: datetime) -> list[str]:
        rows = await self._query(
            "SELECT DISTINCT agent_id FROM turns "
            "WHERE ingested_at > {since:DateTime64(3)} AND ingested_at <= {now:DateTime64(3)}",
            {"since": since, "now": now},
        )
        return sorted(str(row["agent_id"]) for row in rows)

    async def release_activity(self, agent_id: str, environment: str = "") -> list[ReleaseActivity]:
        scope = " AND environment = {env:String}" if environment else ""
        rows = await self._query(
            "SELECT release, max(start_ts) AS last_seen, count() AS turn_count "
            f"FROM turns FINAL WHERE agent_id = {{a:String}}{scope} GROUP BY release",
            {"a": agent_id, "env": environment},
        )
        return [
            ReleaseActivity(
                release=str(row["release"]),
                last_seen=_dt(row["last_seen"]),
                turn_count=int(row["turn_count"]),
            )
            for row in rows
        ]

    async def agent_activity(self, agent_id: str, now: datetime) -> AgentActivity:
        rows = await self._query(
            "SELECT count() AS turns_24h, countIf(release = 'untagged') AS untagged_24h, "
            "groupUniqArray(environment) AS environments_24h, max(start_ts) AS last_turn_at "
            "FROM turns FINAL WHERE agent_id = {a:String} "
            "AND start_ts >= {now:DateTime64(3)} - INTERVAL 24 HOUR",
            {"a": agent_id, "now": now},
        )
        if not rows or int(rows[0]["turns_24h"]) == 0:
            return AgentActivity(0, 0, [], None)
        row = rows[0]
        return AgentActivity(
            turns_24h=int(row["turns_24h"]),
            untagged_24h=int(row["untagged_24h"]),
            environments_24h=sorted(_strings(row["environments_24h"])),
            last_turn_at=_opt_dt(row["last_turn_at"]),
        )

    async def purge_agent(self, agent_id: str, sync: bool = False) -> None:
        settings = {"mutations_sync": 2 if sync else 0}
        parameters = {"agent_id": agent_id}
        await self.client.command(
            "ALTER TABLE spans DELETE WHERE agent_hint = {agent_id:String} "
            "OR (source_id, trace_id) IN "
            "(SELECT source_id, trace_id FROM trace_state WHERE agent_id = {agent_id:String}) "
            "OR (source_id, trace_id) IN "
            "(SELECT source_id, trace_id FROM turns WHERE agent_id = {agent_id:String})",
            parameters=parameters,
            settings=settings,
        )
        await self.client.command(
            "ALTER TABLE trace_state DELETE WHERE agent_id = {agent_id:String}",
            parameters=parameters,
            settings=settings,
        )
        for table in _PURGE_TABLES:
            await self.client.command(
                f"ALTER TABLE {table} DELETE WHERE agent_id = {{agent_id:String}}",
                parameters=parameters,
                settings=settings,
            )

    async def purge_source(self, source_id: str, sync: bool = False) -> None:
        settings = {"mutations_sync": 2 if sync else 0}
        parameters = {"source_id": source_id}
        for table in ("spans", "trace_state"):
            await self.client.command(
                f"ALTER TABLE {table} DELETE WHERE source_id = {{source_id:String}}",
                parameters=parameters,
                settings=settings,
            )


def _span_from(row: dict[str, Any]) -> SpanRow:
    return SpanRow(
        source_id=str(row["source_id"]),
        trace_id=str(row["trace_id"]),
        span_id=str(row["span_id"]),
        parent_span_id=str(row["parent_span_id"]),
        kind=SpanKind(str(row["kind"])),
        name=str(row["name"]),
        start_ts=_dt(row["start_ts"]),
        end_ts=_dt(row["end_ts"]),
        status=SpanStatus(str(row["status"])),
        error_type=str(row["error_type"]),
        agent_hint=str(row["agent_hint"]),
        attributes=_attrs(row["attributes"]),
        request_model=str(row["request_model"]),
        response_model=str(row["response_model"]),
        input_tokens=_opt_int(row["input_tokens"]),
        output_tokens=_opt_int(row["output_tokens"]),
        cost_usd=None if row["cost_usd"] is None else float(row["cost_usd"]),
        tool_name=str(row["tool_name"]),
        tool_call_id=str(row["tool_call_id"]),
        args_hash=str(row["args_hash"]),
        output_chars=_opt_int(row["output_chars"]),
        output_json_valid=_opt_bool(row["output_json_valid"]),
        late=bool(int(row["late"])),
        ingested_at=_dt(row["ingested_at"]),
    )


def _trace_from(row: dict[str, Any]) -> TraceStateRow:
    return TraceStateRow(
        source_id=str(row["source_id"]),
        trace_id=str(row["trace_id"]),
        first_span_at=_dt(row["first_span_at"]),
        last_span_at=_dt(row["last_span_at"]),
        span_count=int(row["span_count"]),
        has_root=bool(int(row["has_root"])),
        agent_id=str(row["agent_id"]),
        root_span_id=str(row["root_span_id"]),
        release=str(row["release"]),
        start_ts=_opt_dt(row["start_ts"]),
        assembled_at=_opt_dt(row["assembled_at"]),
        assembled_version=int(row["assembled_version"]),
        content_hash=str(row["content_hash"]),
        updated_at=_dt(row["updated_at"]),
    )


def _turn_values(row: TurnRow) -> list[Any]:
    return [
        row.agent_id,
        row.release,
        row.start_ts,
        row.turn_id,
        row.trace_id,
        row.root_span_id,
        row.source_id,
        row.environment,
        row.prompt_version,
        row.session_id,
        _flag(row.session_inferred),
        row.surface,
        row.end_ts,
        row.latency_ms,
        row.llm_calls,
        row.llm_errors,
        row.tool_calls,
        row.tool_errors,
        row.tool_retries,
        _opt_flag(row.loop_flag),
        _flag(row.zero_tool_flag),
        row.input_tokens,
        row.output_tokens,
        row.output_chars,
        row.cost_usd,
        row.primary_response_model,
        list(row.response_models),
        _opt_flag(row.format_ok),
        _flag(row.late),
        _flag(row.partial),
        row.source.value,
        row.ingested_at,
        row.version,
    ]
