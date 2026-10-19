from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from apgar.domain.enums import SpanStatus
from apgar.domain.models import SpanRow, ToolCallRow


@dataclass(slots=True)
class TurnKeyInfo:
    agent_id: str
    release: str
    turn_start_ts: datetime
    turn_id: str
    session_id: str
    surface: str
    version: int


_UINT32_MAX = 4_294_967_295


def elapsed_ms(start: datetime, end: datetime) -> int:
    millis = int((end - start).total_seconds() * 1000)
    if millis < 0:
        return 0
    if millis > _UINT32_MAX:
        return _UINT32_MAX
    return millis


def build_tool_calls(tool_spans: list[SpanRow], turn: TurnKeyInfo) -> list[ToolCallRow]:
    ordered = sorted(tool_spans, key=lambda span: (span.start_ts, span.span_id))
    rows: list[ToolCallRow] = []
    for span in ordered:
        duration_ms = elapsed_ms(span.start_ts, span.end_ts)
        if span.args_hash == "":
            is_retry = None
        else:
            is_retry = any(
                earlier.tool_name == span.tool_name
                and earlier.args_hash == span.args_hash
                and earlier.status == SpanStatus.error
                for earlier in rows
            )
        rows.append(
            ToolCallRow(
                agent_id=turn.agent_id,
                release=turn.release,
                turn_start_ts=turn.turn_start_ts,
                turn_id=turn.turn_id,
                tool_call_id=span.span_id,
                session_id=turn.session_id,
                tool_name=span.tool_name,
                call_start_ts=span.start_ts,
                duration_ms=duration_ms,
                status=span.status,
                error_type=span.error_type,
                args_hash=span.args_hash,
                is_retry=is_retry,
                surface=turn.surface,
                version=turn.version,
            )
        )
    return rows


def loop_flag(tool_calls: list[ToolCallRow]) -> bool | None:
    for index in range(len(tool_calls) - 2):
        group = tool_calls[index : index + 3]
        name = group[0].tool_name
        args = group[0].args_hash
        if args and all(call.tool_name == name and call.args_hash == args for call in group):
            return True
    if any(call.args_hash == "" for call in tool_calls):
        return None
    return False


def tool_retries(tool_calls: list[ToolCallRow]) -> int | None:
    if not tool_calls or any(call.args_hash == "" for call in tool_calls):
        return None
    return sum(1 for call in tool_calls if call.is_retry is True)
