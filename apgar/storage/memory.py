from __future__ import annotations

import copy
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import replace
from datetime import datetime, timedelta

from apgar.domain.enums import (
    NotificationChannel,
    NotificationStatus,
    SpanStatus,
)
from apgar.domain.models import (
    Agent,
    Connection,
    IngestToken,
    JobRequest,
    Notification,
    Release,
    ReleaseEvent,
    SpanRow,
    SyncState,
    ToolCallRow,
    TraceStateRow,
    TurnKey,
    TurnRow,
    VerdictEvaluation,
)
from apgar.domain.retention import SESSION_LOOKBACK_DAYS
from apgar.domain.sessions import SessionFields, compute_session_fields
from apgar.security import SecretBox
from apgar.storage.arm import ScopedTurn, ToolFact, assemble_arm
from apgar.storage.clickhouse.migrate import EXPECTED_SCHEMA_VERSION
from apgar.storage.secrets import open_config, seal_config
from apgar.storage.types import (
    AgentActivity,
    ArmData,
    ArmQuery,
    ReleaseActivity,
    ReleaseFilters,
)


def _in_arm_scope(row: TurnRow, query: ArmQuery) -> bool:
    if row.agent_id != query.agent_id or row.release != query.release:
        return False
    if row.start_ts < query.window_start or row.start_ts >= query.window_end:
        return False
    return not query.environment or row.environment == query.environment


def _scoped_turn(row: TurnRow, field: SessionFields) -> ScopedTurn:
    return ScopedTurn(
        turn_id=row.turn_id,
        trace_id=row.trace_id,
        session_id=row.session_id,
        start_ts=row.start_ts,
        end_ts=row.end_ts,
        surface=row.surface,
        depth_bucket=field.depth_bucket,
        response_model=row.primary_response_model,
        prompt_version=row.prompt_version,
        turn_index=field.turn_index,
        mixed_session=field.mixed_session,
        session_inferred=row.session_inferred,
        session_closed=field.session_closed,
        session_first_start=field.session_first_start,
        llm_error=row.llm_errors > 0,
        tool_call_count=row.tool_calls,
        tool_error_count=row.tool_errors,
        zero_tool=row.zero_tool_flag,
        loop_flag=row.loop_flag,
        format_ok=row.format_ok,
        output_tokens=row.output_tokens,
        output_chars=row.output_chars,
        latency_ms=row.latency_ms,
        cost_usd=row.cost_usd,
        is_late=row.late,
    )


def _wins(candidate: datetime, current: datetime | None) -> bool:
    return current is None or candidate >= current


def _copy[T](value: T) -> T:
    return copy.deepcopy(value)


def _copies[T](rows: Sequence[T]) -> list[T]:
    return [_copy(row) for row in rows]


class InMemoryEventStore:
    def __init__(self) -> None:
        self._spans: dict[tuple[str, str, str], SpanRow] = {}
        self._spans_by_trace: dict[tuple[str, str], dict[str, SpanRow]] = {}
        self._trace_state: dict[tuple[str, str], TraceStateRow] = {}
        self._turns: dict[tuple[str, str, datetime, str], TurnRow] = {}
        self._turns_by_trace: dict[str, TurnRow] = {}
        self._tools: dict[tuple[str, str, datetime, str, str], ToolCallRow] = {}

    async def insert_spans(self, rows: Sequence[SpanRow]) -> None:
        for row in rows:
            key = (row.source_id, row.trace_id, row.span_id)
            current = self._spans.get(key)
            if current is not None and row.ingested_at < current.ingested_at:
                continue
            stored = _copy(row)
            self._spans[key] = stored
            bucket = self._spans_by_trace.setdefault((row.source_id, row.trace_id), {})
            bucket[row.span_id] = stored

    async def read_trace_state(
        self, keys: Sequence[tuple[str, str]]
    ) -> dict[tuple[str, str], TraceStateRow]:
        return {key: _copy(self._trace_state[key]) for key in keys if key in self._trace_state}

    async def upsert_trace_state(self, rows: Sequence[TraceStateRow]) -> None:
        for row in rows:
            key = (row.source_id, row.trace_id)
            current = self._trace_state.get(key)
            if current is None or row.updated_at >= current.updated_at:
                self._trace_state[key] = _copy(row)

    async def traces_due_for_assembly(
        self,
        now: datetime,
        quiet_seconds: int,
        max_age_seconds: int,
        limit: int,
    ) -> list[TraceStateRow]:
        quiet_cutoff = now - timedelta(seconds=quiet_seconds)
        age_cutoff = now - timedelta(seconds=max_age_seconds)
        due = [
            row
            for row in self._trace_state.values()
            if (
                (row.has_root and row.last_span_at <= quiet_cutoff)
                or row.first_span_at <= age_cutoff
            )
            and (row.assembled_at is None or row.assembled_at < row.last_span_at)
        ]
        due.sort(key=lambda row: (row.last_span_at, row.trace_id))
        return _copies(due[:limit])

    async def spans_of_trace(self, source_id: str, trace_id: str) -> list[SpanRow]:
        rows = list(self._spans_by_trace.get((source_id, trace_id), {}).values())
        rows.sort(key=lambda row: (row.start_ts, row.span_id))
        return _copies(rows)

    async def spans_of_traces(
        self, keys: Sequence[tuple[str, str]]
    ) -> dict[tuple[str, str], list[SpanRow]]:
        return {key: await self.spans_of_trace(key[0], key[1]) for key in keys}

    async def find_turn_by_trace(self, trace_id: str) -> TurnKey | None:
        best = self._turns_by_trace.get(trace_id)
        if best is None:
            return None
        return TurnKey(
            agent_id=best.agent_id,
            release=best.release,
            start_ts=best.start_ts,
            turn_id=best.turn_id,
            version=best.version,
        )

    async def upsert_turns(self, rows: Sequence[TurnRow]) -> None:
        for row in rows:
            key = (row.agent_id, row.release, row.start_ts, row.turn_id)
            current = self._turns.get(key)
            if current is not None and row.version < current.version:
                continue
            stored = _copy(row)
            self._turns[key] = stored
            best = self._turns_by_trace.get(row.trace_id)
            if best is None or stored.version >= best.version:
                self._turns_by_trace[row.trace_id] = stored

    async def insert_tool_calls(self, rows: Sequence[ToolCallRow]) -> None:
        for row in rows:
            key = (row.agent_id, row.release, row.turn_start_ts, row.turn_id, row.tool_call_id)
            current = self._tools.get(key)
            if current is None or row.version >= current.version:
                self._tools[key] = _copy(row)

    async def load_arm(self, query: ArmQuery) -> ArmData:
        lookback = query.window_start - timedelta(days=SESSION_LOOKBACK_DAYS)
        scope_sessions = {
            row.session_id for row in self._turns.values() if _in_arm_scope(row, query)
        }
        context = [
            row
            for row in self._turns.values()
            if row.agent_id == query.agent_id
            and row.session_id in scope_sessions
            and row.start_ts >= lookback
        ]
        fields = compute_session_fields(context, query.now)
        scoped: list[ScopedTurn] = []
        for row in context:
            if not _in_arm_scope(row, query):
                continue
            field = fields.get(row.turn_id)
            if field is None:
                continue
            scoped.append(_scoped_turn(row, field))
        facts = [
            ToolFact(
                turn_id=row.turn_id,
                session_id=row.session_id,
                tool_name=row.tool_name,
                is_error=row.status is SpanStatus.error,
                has_args_hash=row.args_hash != "",
                is_retry=row.is_retry,
            )
            for row in self._tools.values()
            if row.agent_id == query.agent_id
            and row.release == query.release
            and query.window_start <= row.turn_start_ts < query.window_end
        ]
        untagged = 0
        if query.count_untagged:
            untagged = sum(
                1
                for row in self._turns.values()
                if row.agent_id == query.agent_id
                and row.release == "untagged"
                and query.window_start <= row.start_ts < query.window_end
            )
        return assemble_arm(scoped, facts, query, untagged)

    async def dirty_agents(self, since: datetime, now: datetime) -> list[str]:
        return sorted(
            {row.agent_id for row in self._turns.values() if since < row.ingested_at <= now}
        )

    async def release_activity(self, agent_id: str, environment: str = "") -> list[ReleaseActivity]:
        grouped: dict[str, list[TurnRow]] = defaultdict(list)
        for row in self._turns.values():
            if row.agent_id == agent_id and (not environment or row.environment == environment):
                grouped[row.release].append(row)
        return [
            ReleaseActivity(
                release=release,
                last_seen=max(row.start_ts for row in items),
                turn_count=len(items),
            )
            for release, items in sorted(grouped.items())
        ]

    async def agent_activity(self, agent_id: str, now: datetime) -> AgentActivity:
        window_start = now - timedelta(hours=24)
        window = [
            row
            for row in self._turns.values()
            if row.agent_id == agent_id and row.start_ts >= window_start
        ]
        if not window:
            return AgentActivity(0, 0, [], None)
        return AgentActivity(
            turns_24h=len(window),
            untagged_24h=sum(1 for row in window if row.release == "untagged"),
            environments_24h=sorted({row.environment for row in window}),
            last_turn_at=max(row.start_ts for row in window),
        )

    async def purge_agent(self, agent_id: str, sync: bool = False) -> None:
        del sync
        trace_keys = {
            (row.source_id, row.trace_id)
            for row in self._trace_state.values()
            if row.agent_id == agent_id
        }
        trace_keys.update(
            (row.source_id, row.trace_id)
            for row in self._turns.values()
            if row.agent_id == agent_id
        )
        trace_ids = {trace_id for _source_id, trace_id in trace_keys}

        def _keep_span(row: SpanRow) -> bool:
            if row.agent_hint == agent_id:
                return False
            return (row.source_id, row.trace_id) not in trace_keys

        self._trace_state = {
            key: row for key, row in self._trace_state.items() if row.agent_id != agent_id
        }
        self._spans = {key: row for key, row in self._spans.items() if _keep_span(row)}
        self._spans_by_trace = {
            key: {span_id: row for span_id, row in rows.items() if _keep_span(row)}
            for key, rows in self._spans_by_trace.items()
        }
        self._spans_by_trace = {key: rows for key, rows in self._spans_by_trace.items() if rows}
        self._turns = {key: row for key, row in self._turns.items() if row.agent_id != agent_id}
        self._turns_by_trace = {
            trace_id: row
            for trace_id, row in self._turns_by_trace.items()
            if row.agent_id != agent_id and trace_id not in trace_ids
        }
        self._tools = {key: row for key, row in self._tools.items() if row.agent_id != agent_id}

    async def purge_source(self, source_id: str, sync: bool = False) -> None:
        del sync
        self._spans = {key: row for key, row in self._spans.items() if row.source_id != source_id}
        self._spans_by_trace = {
            key: rows for key, rows in self._spans_by_trace.items() if key[0] != source_id
        }
        self._trace_state = {
            key: row for key, row in self._trace_state.items() if row.source_id != source_id
        }


class InMemoryMetaStore:
    def __init__(self, box: SecretBox | None = None) -> None:
        self._box = box
        self._sealed: dict[str, str] = {}
        self._agents: dict[str, tuple[Agent, bool]] = {}
        self._connections: dict[str, tuple[Connection, bool]] = {}
        self._ingest_tokens: dict[str, tuple[IngestToken, bool]] = {}
        self._settings: dict[str, tuple[str, datetime, bool]] = {}
        self._sync: dict[str, tuple[SyncState, bool]] = {}
        self._releases: dict[tuple[str, str], Release] = {}
        self._release_events: list[ReleaseEvent] = []
        self._evaluations: list[VerdictEvaluation] = []
        self._notifications: dict[tuple[str, NotificationChannel], Notification] = {}
        self._jobs: dict[str, JobRequest] = {}

    async def schema_version(self) -> int:
        return EXPECTED_SCHEMA_VERSION

    async def list_agents(
        self, include_demo: bool = True, include_deleted: bool = False
    ) -> list[Agent]:
        rows: list[Agent] = []
        for agent, is_deleted in self._agents.values():
            if is_deleted:
                continue
            if agent.deleted_at is not None and not include_deleted:
                continue
            if agent.is_demo and not include_demo:
                continue
            rows.append(agent)
        rows.sort(key=lambda agent: agent.name)
        return _copies(rows)

    async def get_agent(self, agent_id: str, include_deleted: bool = False) -> Agent | None:
        row = self._agents.get(agent_id)
        if row is None or row[1]:
            return None
        agent = row[0]
        if agent.deleted_at is not None and not include_deleted:
            return None
        return _copy(agent)

    async def get_agent_by_name(self, name: str) -> Agent | None:
        for agent, is_deleted in self._agents.values():
            if is_deleted or agent.deleted_at is not None:
                continue
            if agent.name == name:
                return _copy(agent)
        return None

    async def upsert_agent(self, agent: Agent) -> None:
        current = self._agents.get(agent.id)
        if current is not None and not _wins(agent.updated_at, current[0].updated_at):
            return
        self._agents[agent.id] = (_copy(agent), False)

    async def delete_agent(self, agent_id: str, now: datetime) -> None:
        row = self._agents.get(agent_id)
        if row is None or row[1] or not _wins(now, row[0].updated_at):
            return
        self._agents[agent_id] = (_copy(replace(row[0], deleted_at=now, updated_at=now)), False)

    async def finalize_agent_deletion(self, agent_id: str, now: datetime) -> None:
        row = self._agents.get(agent_id)
        if row is None or not _wins(now, row[0].updated_at):
            return
        self._agents[agent_id] = (_copy(replace(row[0], updated_at=now)), True)

    def _view_connection(self, connection: Connection) -> Connection:
        sealed = self._sealed.get(connection.id)
        if sealed is None:
            return _copy(connection)
        return _copy(replace(connection, config=open_config(sealed, self._box)))

    async def list_connections(self) -> list[Connection]:
        rows = [
            self._view_connection(item)
            for item, is_deleted in self._connections.values()
            if not is_deleted
        ]
        rows.sort(key=lambda item: item.name)
        return rows

    async def get_connection(self, connection_id: str) -> Connection | None:
        row = self._connections.get(connection_id)
        if row is None or row[1]:
            return None
        return self._view_connection(row[0])

    async def connection_ciphertext(self, connection_id: str) -> str | None:
        row = self._connections.get(connection_id)
        if row is None or row[1]:
            return None
        return self._sealed.get(connection_id)

    async def upsert_connection(self, connection: Connection) -> None:
        current = self._connections.get(connection.id)
        if current is not None and not _wins(connection.updated_at, current[0].updated_at):
            return
        self._sealed[connection.id] = seal_config(connection.config, self._box)
        self._connections[connection.id] = (_copy(connection), False)

    async def delete_connection(self, connection_id: str, now: datetime) -> None:
        row = self._connections.get(connection_id)
        if row is None or row[1] or not _wins(now, row[0].updated_at):
            return
        self._connections[connection_id] = (_copy(replace(row[0], updated_at=now)), True)

    async def list_ingest_tokens(self) -> list[IngestToken]:
        rows = [item for item, is_deleted in self._ingest_tokens.values() if not is_deleted]
        rows.sort(key=lambda item: item.created_at)
        return _copies(rows)

    async def get_ingest_token_by_hash(self, token_hash: str) -> IngestToken | None:
        for token, is_deleted in self._ingest_tokens.values():
            if not is_deleted and token.token_hash == token_hash:
                return _copy(token)
        return None

    async def upsert_ingest_token(self, token: IngestToken) -> None:
        current = self._ingest_tokens.get(token.id)
        if current is not None and not _wins(token.updated_at, current[0].updated_at):
            return
        self._ingest_tokens[token.id] = (_copy(token), False)

    async def get_setting(self, key: str) -> str | None:
        row = self._settings.get(key)
        if row is None or row[2]:
            return None
        return row[0]

    async def set_setting(self, key: str, value: str, now: datetime) -> None:
        current = self._settings.get(key)
        if current is not None and not _wins(now, current[1]):
            return
        self._settings[key] = (value, now, False)

    async def delete_setting(self, key: str, now: datetime) -> None:
        current = self._settings.get(key)
        if current is not None and not _wins(now, current[1]):
            return
        value = "" if current is None else current[0]
        self._settings[key] = (value, now, True)

    async def list_settings(self, prefix: str) -> dict[str, str]:
        return {
            key: value
            for key, (value, _updated_at, is_deleted) in sorted(self._settings.items())
            if not is_deleted and key.startswith(prefix)
        }

    async def get_sync_state(self, connection_id: str) -> SyncState | None:
        row = self._sync.get(connection_id)
        if row is None or row[1]:
            return None
        return _copy(row[0])

    async def upsert_sync_state(self, state: SyncState) -> None:
        current = self._sync.get(state.connection_id)
        if current is not None and not _wins(state.updated_at, current[0].updated_at):
            return
        self._sync[state.connection_id] = (_copy(state), False)

    async def get_release(self, agent_id: str, release: str) -> Release | None:
        stored = self._releases.get((agent_id, release))
        if stored is None:
            return None
        return _copy(stored)

    async def list_releases(self, filters: ReleaseFilters) -> list[Release]:
        rows = list(self._releases.values())
        if filters.agent_id is not None:
            rows = [row for row in rows if row.agent_id == filters.agent_id]
        if filters.final is not None:
            rows = [row for row in rows if row.final == filters.final]
        rows.sort(key=lambda row: (row.agent_id, row.release))
        return _copies(rows[filters.offset : filters.offset + filters.limit])

    async def upsert_release(self, release: Release) -> None:
        key = (release.agent_id, release.release)
        current = self._releases.get(key)
        if current is not None and not _wins(release.updated_at, current.updated_at):
            return
        self._releases[key] = _copy(release)

    async def append_release_event(self, event: ReleaseEvent) -> None:
        self._release_events.append(_copy(event))

    async def release_events(self, agent_id: str, release: str) -> list[ReleaseEvent]:
        rows = [
            event
            for event in self._release_events
            if event.agent_id == agent_id and event.release == release
        ]
        rows.sort(key=lambda event: (event.ts, event.type.value))
        return _copies(rows)

    async def append_evaluation(self, evaluation: VerdictEvaluation) -> None:
        self._evaluations.append(_copy(evaluation))

    async def list_evaluations(
        self, agent_id: str, release: str, limit: int
    ) -> list[VerdictEvaluation]:
        rows = [
            item
            for item in self._evaluations
            if item.agent_id == agent_id and item.release == release
        ]
        rows.sort(key=lambda item: item.evaluated_at, reverse=True)
        return _copies(rows[:limit])

    async def upsert_notification(self, notification: Notification) -> None:
        key = (notification.idempotency_key, notification.channel)
        current = self._notifications.get(key)
        if current is not None and not _wins(notification.updated_at, current.updated_at):
            return
        self._notifications[key] = _copy(notification)

    async def get_notification(
        self, idempotency_key: str, channel: NotificationChannel
    ) -> Notification | None:
        stored = self._notifications.get((idempotency_key, channel))
        if stored is None:
            return None
        return _copy(stored)

    async def due_notifications(
        self,
        now: datetime,
        limit: int,
    ) -> list[Notification]:
        rows = [
            item
            for item in self._notifications.values()
            if item.status == NotificationStatus.pending and item.next_attempt_at <= now
        ]
        rows.sort(key=lambda item: (item.next_attempt_at, item.idempotency_key))
        return _copies(rows[:limit])

    async def list_notifications(
        self, status: NotificationStatus | None, limit: int
    ) -> list[Notification]:
        rows = list(self._notifications.values())
        if status is not None:
            rows = [item for item in rows if item.status == status]
        rows.sort(key=lambda item: item.created_at, reverse=True)
        return _copies(rows[:limit])

    async def enqueue_job(self, job: JobRequest) -> None:
        current = self._jobs.get(job.id)
        if current is not None and not _wins(job.updated_at, current.updated_at):
            return
        self._jobs[job.id] = _copy(job)

    async def pending_jobs(self, limit: int) -> list[JobRequest]:
        rows = [job for job in self._jobs.values() if job.processed_at is None]
        rows.sort(key=lambda job: (job.requested_at, job.id))
        return _copies(rows[:limit])

    async def complete_job(self, job: JobRequest, now: datetime) -> None:
        updated = replace(job, processed_at=now, updated_at=now)
        current = self._jobs.get(job.id)
        if current is not None and not _wins(updated.updated_at, current.updated_at):
            return
        self._jobs[job.id] = _copy(updated)
