from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from apgar.domain.enums import (
    ConnectionStatus,
    ConnectionType,
    JobRequestKind,
    NotificationChannel,
    NotificationEvent,
    NotificationStatus,
    OutputFormat,
    ReasonCode,
    ReleaseEventType,
    Source,
    SpanKind,
    SpanStatus,
    VerdictState,
)
from apgar.domain.settings import AgentFilter, ReleaseSettings, SurfaceMapping, VerdictSettings


@dataclass(slots=True)
class SpanRow:
    source_id: str
    trace_id: str
    span_id: str
    parent_span_id: str
    kind: SpanKind
    name: str
    start_ts: datetime
    end_ts: datetime
    status: SpanStatus
    error_type: str
    agent_hint: str
    attributes: dict[str, str]
    request_model: str
    response_model: str
    input_tokens: int | None
    output_tokens: int | None
    cost_usd: float | None
    tool_name: str
    tool_call_id: str
    args_hash: str
    output_chars: int | None
    output_json_valid: bool | None
    late: bool
    ingested_at: datetime


@dataclass(slots=True)
class TraceStateRow:
    source_id: str
    trace_id: str
    first_span_at: datetime
    last_span_at: datetime
    span_count: int
    has_root: bool
    agent_id: str
    root_span_id: str
    release: str
    start_ts: datetime | None
    assembled_at: datetime | None
    assembled_version: int
    content_hash: str
    updated_at: datetime


@dataclass(slots=True)
class TurnRow:
    agent_id: str
    release: str
    start_ts: datetime
    turn_id: str
    trace_id: str
    root_span_id: str
    source_id: str
    environment: str
    prompt_version: str
    session_id: str
    session_inferred: bool
    surface: str
    end_ts: datetime
    latency_ms: int
    llm_calls: int
    llm_errors: int
    tool_calls: int
    tool_errors: int
    tool_retries: int | None
    loop_flag: bool | None
    zero_tool_flag: bool
    input_tokens: int | None
    output_tokens: int | None
    output_chars: int | None
    cost_usd: float | None
    primary_response_model: str
    response_models: list[str]
    format_ok: bool | None
    late: bool
    partial: bool
    source: Source
    ingested_at: datetime
    version: int


@dataclass(slots=True)
class ToolCallRow:
    agent_id: str
    release: str
    turn_start_ts: datetime
    turn_id: str
    tool_call_id: str
    session_id: str
    tool_name: str
    call_start_ts: datetime
    duration_ms: int
    status: SpanStatus
    error_type: str
    args_hash: str
    is_retry: bool | None
    surface: str
    version: int


@dataclass(slots=True)
class TurnKey:
    agent_id: str
    release: str
    start_ts: datetime
    turn_id: str
    version: int


@dataclass(slots=True)
class Agent:
    id: str
    name: str
    source: Source
    langfuse_connection_id: str
    filter: AgentFilter | None
    environment: str
    surface_mapping: SurfaceMapping
    release_settings: ReleaseSettings
    metric_settings: dict[str, dict[str, Any]]
    verdict_settings: VerdictSettings
    output_format: OutputFormat
    slack_connection_id: str
    is_demo: bool
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None


@dataclass(slots=True)
class Connection:
    id: str
    name: str
    type: ConnectionType
    config: dict[str, Any]
    status: ConnectionStatus
    last_checked_at: datetime | None
    last_error: str
    created_at: datetime
    updated_at: datetime


@dataclass(slots=True)
class IngestToken:
    id: str
    name: str
    token_hash: str
    token_prefix: str
    agent_id: str
    auto_create_agents: bool
    created_at: datetime
    revoked_at: datetime | None
    updated_at: datetime


@dataclass(slots=True)
class Setting:
    key: str
    value: str
    updated_at: datetime


@dataclass(slots=True)
class SyncState:
    connection_id: str
    watermark: datetime | None
    last_success_at: datetime | None
    last_error: str
    last_error_at: datetime | None
    lag_seconds: int | None
    in_progress: bool
    updated_at: datetime


@dataclass(slots=True)
class Release:
    agent_id: str
    release: str
    first_seen: datetime
    state: VerdictState
    reason: ReasonCode
    final: bool
    final_at: datetime | None
    selected_baseline_release: str
    selected_baseline_mode: str
    baseline_unverified: bool
    verdict_summary: dict[str, Any]
    verdict_updated_at: datetime | None
    last_seen: datetime | None
    turn_count: int
    updated_at: datetime


@dataclass(slots=True)
class ReleaseEvent:
    agent_id: str
    release: str
    ts: datetime
    type: ReleaseEventType
    payload: dict[str, Any]
    actor: str


@dataclass(slots=True)
class VerdictEvaluation:
    agent_id: str
    release: str
    evaluated_at: datetime
    manual: bool
    seed: str
    baseline_release: str
    baseline_mode: str
    baseline_unverified: bool
    window_start: datetime | None
    window_end: datetime | None
    n_candidate_turns: int
    n_baseline_turns: int
    n_candidate_sessions: int
    n_baseline_sessions: int
    n_excluded_mixed: int
    n_excluded_untagged: int
    n_excluded_late: int
    state: VerdictState
    reason: ReasonCode
    final: bool
    metrics: dict[str, Any]
    slices: dict[str, Any]
    duration_ms: int


@dataclass(slots=True)
class Notification:
    id: str
    agent_id: str
    release: str
    event: NotificationEvent
    idempotency_key: str
    channel: NotificationChannel
    connection_id: str
    status: NotificationStatus
    attempts: int
    next_attempt_at: datetime
    last_error: str
    payload: dict[str, Any]
    created_at: datetime
    updated_at: datetime


@dataclass(slots=True)
class JobRequest:
    id: str
    agent_id: str
    release: str
    kind: JobRequestKind
    payload: dict[str, Any]
    requested_at: datetime
    processed_at: datetime | None
    updated_at: datetime
