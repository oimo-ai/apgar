from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True)
class ReleaseFilters:
    agent_id: str | None = None
    final: bool | None = None
    limit: int = 500
    offset: int = 0


@dataclass(slots=True)
class ReleaseActivity:
    release: str
    last_seen: datetime
    turn_count: int


@dataclass(slots=True)
class AgentActivity:
    turns_24h: int
    untagged_24h: int
    environments_24h: list[str]
    last_turn_at: datetime | None


@dataclass(slots=True)
class ArmQuery:
    agent_id: str
    release: str
    window_start: datetime
    window_end: datetime
    environment: str
    include_mixed: bool
    session_min_first_start: datetime | None
    hour_of_day_filter: frozenset[int] | None
    now: datetime
    count_untagged: bool


@dataclass(slots=True)
class ArmTurn:
    turn_id: str
    trace_id: str
    session_id: str
    start_ts: datetime
    end_ts: datetime
    surface: str
    depth_bucket: str
    response_model: str
    prompt_version: str
    turn_index: int
    mixed_session: bool
    session_inferred: bool
    session_closed: bool
    llm_error: bool
    tool_calls: int
    tool_errors: int
    zero_tool: bool
    loop_flag: bool | None
    format_ok: bool | None
    output_tokens: int | None
    output_chars: int | None
    latency_ms: int
    cost_usd: float | None
    tools_called: list[str]


@dataclass(slots=True)
class ArmToolCall:
    turn_id: str
    session_id: str
    tool_name: str
    is_error: bool
    has_args_hash: bool
    is_retry: bool | None
    surface: str
    depth_bucket: str
    response_model: str
    prompt_version: str


@dataclass(slots=True)
class ArmData:
    turns: list[ArmTurn]
    tool_calls: list[ArmToolCall]
    n_excluded_mixed: int
    n_excluded_late: int
    n_excluded_untagged: int
