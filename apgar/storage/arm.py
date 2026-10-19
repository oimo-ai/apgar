from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime

from apgar.storage.types import ArmData, ArmQuery, ArmToolCall, ArmTurn


@dataclass(slots=True)
class ScopedTurn:
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
    session_first_start: datetime
    llm_error: bool
    tool_call_count: int
    tool_error_count: int
    zero_tool: bool
    loop_flag: bool | None
    format_ok: bool | None
    output_tokens: int | None
    output_chars: int | None
    latency_ms: int
    cost_usd: float | None
    is_late: bool


@dataclass(slots=True)
class ToolFact:
    turn_id: str
    session_id: str
    tool_name: str
    is_error: bool
    has_args_hash: bool
    is_retry: bool | None


def _hour(moment: datetime) -> int:
    current = moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)
    return current.astimezone(UTC).hour


def _aware(moment: datetime) -> datetime:
    if moment.tzinfo is None:
        return moment.replace(tzinfo=UTC)
    return moment.astimezone(UTC)


def assemble_arm(
    scoped: list[ScopedTurn],
    tools: list[ToolFact],
    query: ArmQuery,
    n_excluded_untagged: int,
) -> ArmData:
    n_excluded_late = sum(1 for turn in scoped if turn.is_late)
    kept: list[ScopedTurn] = []
    minimum = query.session_min_first_start
    hours = query.hour_of_day_filter
    for turn in scoped:
        if turn.is_late:
            continue
        if minimum is not None and _aware(turn.session_first_start) < _aware(minimum):
            continue
        if hours is not None and _hour(turn.start_ts) not in hours:
            continue
        kept.append(turn)
    included = kept if query.include_mixed else [turn for turn in kept if not turn.mixed_session]
    names: dict[str, set[str]] = defaultdict(set)
    for tool in tools:
        names[tool.turn_id].add(tool.tool_name)
    by_id = {turn.turn_id: turn for turn in kept}

    def _arm_turn(turn: ScopedTurn) -> ArmTurn:
        return ArmTurn(
            turn_id=turn.turn_id,
            trace_id=turn.trace_id,
            session_id=turn.session_id,
            start_ts=_aware(turn.start_ts),
            end_ts=_aware(turn.end_ts),
            surface=turn.surface,
            depth_bucket=turn.depth_bucket,
            response_model=turn.response_model,
            prompt_version=turn.prompt_version,
            turn_index=turn.turn_index,
            mixed_session=turn.mixed_session,
            session_inferred=turn.session_inferred,
            session_closed=turn.session_closed,
            llm_error=turn.llm_error,
            tool_calls=turn.tool_call_count,
            tool_errors=turn.tool_error_count,
            zero_tool=turn.zero_tool,
            loop_flag=turn.loop_flag,
            format_ok=turn.format_ok,
            output_tokens=turn.output_tokens,
            output_chars=turn.output_chars,
            latency_ms=turn.latency_ms,
            cost_usd=turn.cost_usd,
            tools_called=sorted(names.get(turn.turn_id, set())),
        )

    def _arm_tool(tool: ToolFact, turn: ScopedTurn) -> ArmToolCall:
        return ArmToolCall(
            turn_id=tool.turn_id,
            session_id=tool.session_id,
            tool_name=tool.tool_name,
            is_error=tool.is_error,
            has_args_hash=tool.has_args_hash,
            is_retry=tool.is_retry,
            surface=turn.surface,
            depth_bucket=turn.depth_bucket,
            response_model=turn.response_model,
            prompt_version=turn.prompt_version,
        )

    included_ids = {turn.turn_id for turn in included}
    arm_tools: list[ArmToolCall] = []
    for tool in tools:
        owner = by_id.get(tool.turn_id)
        if owner is not None and tool.turn_id in included_ids:
            arm_tools.append(_arm_tool(tool, owner))
    return ArmData(
        turns=[_arm_turn(turn) for turn in included],
        tool_calls=arm_tools,
        n_excluded_mixed=sum(1 for turn in kept if turn.mixed_session),
        n_excluded_late=n_excluded_late,
        n_excluded_untagged=n_excluded_untagged,
    )
