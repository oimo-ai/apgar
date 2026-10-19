from __future__ import annotations

from datetime import datetime, timedelta

from apgar.assembly.tools import TurnKeyInfo, build_tool_calls, loop_flag, tool_retries
from apgar.domain.enums import SpanKind, SpanStatus
from apgar.domain.models import SpanRow
from tests.support import make_span


def _tool(
    now: datetime, span_id: str, name: str, args: str, status: SpanStatus, offset: int
) -> SpanRow:
    start = now + timedelta(seconds=offset)
    return make_span(
        now,
        span_id=span_id,
        kind=SpanKind.execute_tool,
        name=name,
        tool_name=name,
        args_hash=args,
        status=status,
        start_ts=start,
        end_ts=start + timedelta(milliseconds=250),
    )


def _turn(now: datetime) -> TurnKeyInfo:
    return TurnKeyInfo("agent", "rel", now, "turn", "session", "", 1)


def test_retry_and_loop(fixed_now: datetime) -> None:
    spans = [
        _tool(fixed_now, "01", "sql_query", "hash-x", SpanStatus.error, 0),
        _tool(fixed_now, "02", "sql_query", "hash-x", SpanStatus.ok, 1),
        _tool(fixed_now, "03", "get_invoice", "hash-y", SpanStatus.ok, 2),
        _tool(fixed_now, "04", "get_invoice", "hash-y", SpanStatus.ok, 3),
        _tool(fixed_now, "05", "get_invoice", "hash-y", SpanStatus.ok, 4),
    ]
    rows = build_tool_calls(spans, _turn(fixed_now))
    assert [row.is_retry for row in rows] == [False, True, False, False, False]
    assert tool_retries(rows) == 1
    assert loop_flag(rows) is True


def test_missing_args_are_null(fixed_now: datetime) -> None:
    spans = [
        _tool(fixed_now, "01", "sql_query", "", SpanStatus.ok, 0),
        _tool(fixed_now, "02", "sql_query", "", SpanStatus.error, 1),
    ]
    rows = build_tool_calls(spans, _turn(fixed_now))
    assert all(row.is_retry is None for row in rows)
    assert loop_flag(rows) is None
    assert tool_retries(rows) is None


def test_no_tool_calls_are_not_a_loop(fixed_now: datetime) -> None:
    assert loop_flag([]) is False
    assert tool_retries([]) is None


def test_duration_clamps_negative(fixed_now: datetime) -> None:
    span = _tool(fixed_now, "01", "sql_query", "h", SpanStatus.ok, 0)
    span.end_ts = span.start_ts - timedelta(seconds=1)
    rows = build_tool_calls([span], _turn(fixed_now))
    assert rows[0].duration_ms == 0


def test_duration_clamps_uint32(fixed_now: datetime) -> None:
    span = _tool(fixed_now, "01", "sql_query", "h", SpanStatus.ok, 0)
    span.end_ts = span.start_ts + timedelta(days=80)
    rows = build_tool_calls([span], _turn(fixed_now))
    assert rows[0].duration_ms == 4_294_967_295
