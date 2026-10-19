from __future__ import annotations

import json
from datetime import timedelta

import pytest

from apgar.config import Settings
from apgar.domain.enums import Source, SpanKind, SpanStatus
from apgar.domain.models import SpanRow
from apgar.normalize.normalizer import MalformedSpan, normalize
from apgar.normalize.otlp import RawSpan, decode_request, iter_raw_spans
from tests.support import FIXTURE_NOW, keys_for, load_fixture


def _spans(name: str, settings: Settings) -> list[SpanRow]:
    rows = []
    for raw in iter_raw_spans(decode_request(load_fixture(name), "application/json", None)):
        rows.append(
            normalize(
                raw,
                source_id="src",
                source=Source.otlp,
                agent_hint="",
                now=FIXTURE_NOW,
                late_days=7,
                keys=keys_for(settings),
            )
        )
    return rows


def test_genai_basic_fields(settings: Settings) -> None:
    root, chat, tool = _spans("genai_basic.json", settings)
    assert root.kind is SpanKind.invoke_agent
    assert root.output_chars and root.output_chars > 0
    assert chat.request_model == "gpt-4.1"
    assert chat.response_model == "gpt-4.1"
    assert chat.input_tokens == 900
    assert chat.output_tokens == 150
    assert chat.cost_usd == pytest.approx(0.003)
    assert tool.kind is SpanKind.execute_tool
    assert tool.tool_name == "sql_query"
    assert tool.tool_call_id == tool.span_id
    assert tool.args_hash != ""


def test_retry_loop_tool_status(settings: Settings) -> None:
    spans = _spans("genai_retry_loop.json", settings)
    tools = [span for span in spans if span.kind is SpanKind.execute_tool]
    assert next(span.status for span in tools) is SpanStatus.error
    assert tools[0].error_type == "ToolError"


def test_no_args_hash_empty(settings: Settings) -> None:
    spans = _spans("genai_no_args.json", settings)
    tools = [span for span in spans if span.kind is SpanKind.execute_tool]
    assert tools
    assert all(span.args_hash == "" for span in tools)


def test_late_flag(settings: Settings) -> None:
    span = _spans("late_span.json", settings)[0]
    assert span.late is True
    assert span.start_ts == FIXTURE_NOW - timedelta(days=8)


def test_status_from_langfuse_level(settings: Settings) -> None:
    raw = RawSpan(
        trace_id="11" * 16,
        span_id="aa" * 8,
        parent_span_id="",
        name="generation",
        start_unix_nano=1_000_000_000,
        end_unix_nano=2_000_000_000,
        attributes={
            "langfuse.observation.level": "ERROR",
            "langfuse.observation.type": "generation",
        },
        status_code=1,
        status_message="boom",
        resource_attributes={},
    )
    span = normalize(
        raw,
        source_id="src",
        source=Source.otlp,
        agent_hint="",
        now=FIXTURE_NOW,
        late_days=7,
        keys=keys_for(settings),
    )
    assert span.status is SpanStatus.error
    assert span.error_type == "boom"


def test_args_hash_canonical_order_independent(settings: Settings) -> None:
    def hashed(arguments: str) -> str:
        raw = RawSpan(
            trace_id="11" * 16,
            span_id="aa" * 8,
            parent_span_id="bb" * 8,
            name="tool",
            start_unix_nano=1_000_000_000,
            end_unix_nano=2_000_000_000,
            attributes={
                "gen_ai.operation.name": "execute_tool",
                "gen_ai.tool.name": "sql_query",
                "gen_ai.tool.call.arguments": arguments,
            },
            status_code=1,
            status_message="",
            resource_attributes={},
        )
        return normalize(
            raw,
            source_id="src",
            source=Source.otlp,
            agent_hint="",
            now=FIXTURE_NOW,
            late_days=7,
            keys=keys_for(settings),
        ).args_hash

    assert hashed(json.dumps({"a": 1, "b": 2})) == hashed(json.dumps({"b": 2, "a": 1}))


def test_zero_start_is_malformed(settings: Settings) -> None:
    raw = RawSpan(
        trace_id="11" * 16,
        span_id="aa" * 8,
        parent_span_id="",
        name="span",
        start_unix_nano=0,
        end_unix_nano=1,
        attributes={},
        status_code=0,
        status_message="",
        resource_attributes={},
    )
    with pytest.raises(MalformedSpan):
        normalize(
            raw,
            source_id="src",
            source=Source.otlp,
            agent_hint="",
            now=FIXTURE_NOW,
            late_days=7,
            keys=keys_for(settings),
        )


def test_end_before_start_is_clamped(settings: Settings) -> None:
    raw = RawSpan(
        trace_id="11" * 16,
        span_id="aa" * 8,
        parent_span_id="",
        name="span",
        start_unix_nano=2_000_000_000,
        end_unix_nano=1_000_000_000,
        attributes={"gen_ai.operation.name": "chat"},
        status_code=0,
        status_message="",
        resource_attributes={},
    )
    span = normalize(
        raw,
        source_id="src",
        source=Source.otlp,
        agent_hint="",
        now=FIXTURE_NOW,
        late_days=7,
        keys=keys_for(settings),
    )
    assert span.end_ts == span.start_ts


def test_content_absent_nulls(settings: Settings) -> None:
    span = _spans("content_absent.json", settings)[0]
    assert span.output_chars is None
    assert span.output_json_valid is None


def test_json_output_valid(settings: Settings) -> None:
    span = _spans("json_output.json", settings)[0]
    assert span.output_json_valid is True


def test_langfuse_usage_json(settings: Settings) -> None:
    spans = _spans("langfuse_otel_basic.json", settings)
    root = spans[0]
    chat = spans[1]
    assert root.kind is SpanKind.invoke_agent
    assert chat.input_tokens == 900
    assert chat.output_tokens == 150
    assert chat.cost_usd == pytest.approx(0.003)


def test_openinference_tool_hash(settings: Settings) -> None:
    tool = _spans("openinference_basic.json", settings)[2]
    assert tool.kind is SpanKind.execute_tool
    assert tool.args_hash != ""


def test_out_of_range_tokens_are_dropped(settings: Settings) -> None:
    raw = RawSpan(
        trace_id="1" * 32,
        span_id="a" * 16,
        parent_span_id="",
        name="chat",
        start_unix_nano=1_791_450_000_000_000_000,
        end_unix_nano=1_791_450_001_000_000_000,
        attributes={
            "gen_ai.operation.name": "chat",
            "gen_ai.usage.input_tokens": -5,
            "gen_ai.usage.output_tokens": float("inf"),
            "gen_ai.usage.cost": float("nan"),
        },
        status_code=1,
        status_message="",
        resource_attributes={},
    )
    span = normalize(
        raw,
        source_id="src",
        source=Source.otlp,
        agent_hint="",
        now=FIXTURE_NOW,
        late_days=7,
        keys=keys_for(settings),
    )
    assert span.input_tokens is None
    assert span.output_tokens is None
    assert span.cost_usd is None
