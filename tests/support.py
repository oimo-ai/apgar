from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from apgar.config import Settings
from apgar.domain.enums import Source, SpanKind, SpanStatus
from apgar.domain.models import SpanRow, TurnRow
from apgar.normalize.normalizer import HmacKeys
from apgar.storage.clickhouse.event_store import ClickHouseEventStore
from apgar.storage.clickhouse.meta_store import ClickHouseMetaStore
from apgar.storage.memory import InMemoryEventStore, InMemoryMetaStore

ChDatabase = tuple[Settings, ClickHouseEventStore, ClickHouseMetaStore]
MemStores = tuple[InMemoryEventStore, InMemoryMetaStore]
FIXTURES = Path(__file__).parent / "fixtures" / "otlp"
FIXTURE_NOW = datetime(2026, 10, 8, 9, 0, tzinfo=UTC)


class Clock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


def load_fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def keys_for(settings: Settings) -> HmacKeys:
    return HmacKeys.from_settings(settings)


def make_span(now: datetime, **overrides: object) -> SpanRow:
    span = SpanRow(
        source_id="src",
        trace_id="11" * 16,
        span_id="aa" * 8,
        parent_span_id="",
        kind=SpanKind.chat,
        name="chat",
        start_ts=now,
        end_ts=now,
        status=SpanStatus.ok,
        error_type="",
        agent_hint="",
        attributes={},
        request_model="",
        response_model="gpt-4.1",
        input_tokens=None,
        output_tokens=None,
        cost_usd=None,
        tool_name="",
        tool_call_id="",
        args_hash="",
        output_chars=None,
        output_json_valid=None,
        late=False,
        ingested_at=now,
    )
    for key, value in overrides.items():
        setattr(span, key, value)
    return span


def make_turn(now: datetime, **overrides: object) -> TurnRow:
    turn = TurnRow(
        agent_id="agent",
        release="rel",
        start_ts=now,
        turn_id="turn",
        trace_id="11" * 16,
        root_span_id="aa" * 8,
        source_id="src",
        environment="production",
        prompt_version="",
        session_id="session",
        session_inferred=False,
        surface="",
        end_ts=now,
        latency_ms=1000,
        llm_calls=1,
        llm_errors=0,
        tool_calls=0,
        tool_errors=0,
        tool_retries=0,
        loop_flag=False,
        zero_tool_flag=True,
        input_tokens=10,
        output_tokens=20,
        output_chars=5,
        cost_usd=0.01,
        primary_response_model="gpt-4.1",
        response_models=["gpt-4.1"],
        format_ok=None,
        late=False,
        partial=False,
        source=Source.otlp,
        ingested_at=now,
        version=1,
    )
    for key, value in overrides.items():
        setattr(turn, key, value)
    return turn
