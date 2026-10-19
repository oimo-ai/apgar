from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from apgar.config import Settings
from apgar.domain.enums import OutputFormat, ReasonCode, Source, VerdictState
from apgar.domain.models import Agent, Release, ToolCallRow, TurnRow
from apgar.domain.settings import VerdictSettings
from apgar.storage.memory import InMemoryEventStore, InMemoryMetaStore
from apgar.verdict.evaluate import Evaluator
from apgar.verdict.pool import InlinePool
from apgar.worker.jobs.release_discovery import new_release

NOW = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)


def _settings(base: Settings) -> Settings:
    return base.model_copy(update={"bootstrap_resamples": 300, "bootstrap_chunk": 100})


def _agent(now: datetime) -> Agent:
    return Agent(
        id="agent-1",
        name="billing-copilot",
        source=Source.otlp,
        langfuse_connection_id="",
        filter=None,
        environment="",
        surface_mapping=__import__(
            "apgar.domain.settings", fromlist=["SurfaceMapping"]
        ).SurfaceMapping(),
        release_settings=__import__(
            "apgar.domain.settings", fromlist=["ReleaseSettings"]
        ).ReleaseSettings(),
        metric_settings={},
        verdict_settings=VerdictSettings(min_turns=40, min_sessions=4, min_turns_slice=10),
        output_format=OutputFormat.text,
        slack_connection_id="",
        is_demo=False,
        created_at=now,
        updated_at=now,
        deleted_at=None,
    )


def _turn(
    release: str,
    index: int,
    session: int,
    *,
    error: bool,
    start: datetime,
) -> tuple[TurnRow, ToolCallRow]:
    turn_id = f"{release}-{index:04d}"
    start_ts = start + timedelta(minutes=index)
    turn = TurnRow(
        agent_id="agent-1",
        release=release,
        start_ts=start_ts,
        turn_id=turn_id,
        trace_id=f"{index:032x}",
        root_span_id="ab" * 8,
        source_id="demo",
        environment="production",
        prompt_version="billing@7",
        session_id=f"{release}-s{session}",
        session_inferred=False,
        surface="web",
        end_ts=start_ts + timedelta(seconds=2),
        latency_ms=1000,
        llm_calls=1,
        llm_errors=0,
        tool_calls=1,
        tool_errors=1 if error else 0,
        tool_retries=0,
        loop_flag=False,
        zero_tool_flag=False,
        input_tokens=10,
        output_tokens=100,
        output_chars=40,
        cost_usd=0.01,
        primary_response_model="gpt-4.1",
        response_models=["gpt-4.1"],
        format_ok=None,
        late=False,
        partial=False,
        source=Source.otlp,
        ingested_at=start_ts,
        version=1,
    )
    tool = ToolCallRow(
        agent_id="agent-1",
        release=release,
        turn_start_ts=start_ts,
        turn_id=turn_id,
        tool_call_id=f"tool-{turn_id}",
        session_id=turn.session_id,
        tool_name="sql_query" if error or index % 3 == 0 else "get_invoice",
        call_start_ts=start_ts,
        duration_ms=10,
        status=__import__("apgar.domain.enums", fromlist=["SpanStatus"]).SpanStatus.error
        if error
        else __import__("apgar.domain.enums", fromlist=["SpanStatus"]).SpanStatus.ok,
        error_type="ToolError" if error else "",
        args_hash="abc",
        is_retry=False,
        surface="web",
        version=1,
    )
    return turn, tool


async def _seed(meta: InMemoryMetaStore, event: InMemoryEventStore, error_rate: float) -> None:
    agent = _agent(NOW)
    await meta.upsert_agent(agent)
    base_start = NOW - timedelta(days=3)
    cand_start = NOW - timedelta(hours=30)
    await meta.upsert_release(
        new_release("agent-1", "base", base_start, ReasonCode.no_baseline, base_start)
    )
    await meta.upsert_release(
        new_release("agent-1", "cand", cand_start, ReasonCode.insufficient_sample, cand_start)
    )
    turns: list[TurnRow] = []
    tools: list[ToolCallRow] = []
    for index in range(80):
        turn, tool = _turn("base", index, index // 5, error=False, start=base_start)
        turns.append(turn)
        tools.append(tool)
        turn, tool = _turn(
            "cand",
            index,
            index // 5,
            error=index / 80 < error_rate,
            start=cand_start,
        )
        turns.append(turn)
        tools.append(tool)
    await event.upsert_turns(turns)
    await event.insert_tool_calls(tools)


async def test_fail_after_two_evaluations(settings: Settings) -> None:
    event, meta = InMemoryEventStore(), InMemoryMetaStore()
    await _seed(meta, event, 0.4)
    agent = await meta.get_agent("agent-1")
    assert agent is not None
    release = await meta.get_release("agent-1", "cand")
    assert release is not None
    evaluator = Evaluator(
        event, meta, _settings(settings), InlinePool(), lambda: NOW, [], asyncio.Lock()
    )
    first = await evaluator.evaluate_release(agent, release, NOW - timedelta(minutes=20), False)
    assert first is not None
    assert first.state is VerdictState.INCONCLUSIVE
    assert first.reason is ReasonCode.fail_candidate
    stored = await meta.get_release("agent-1", "cand")
    assert stored is not None
    second = await evaluator.evaluate_release(agent, stored, NOW, False)
    assert second is not None
    assert second.state is VerdictState.FAIL
    assert second.reason is ReasonCode.confirmed
    assert second.metrics["items"]["tool_error_rate"]["status"] == "FAIL"


async def test_pass_equal_arms(settings: Settings) -> None:
    event, meta = InMemoryEventStore(), InMemoryMetaStore()
    await _seed(meta, event, 0.0)
    agent = await meta.get_agent("agent-1")
    assert agent is not None
    release = await meta.get_release("agent-1", "cand")
    assert release is not None
    evaluator = Evaluator(
        event, meta, _settings(settings), InlinePool(), lambda: NOW, [], asyncio.Lock()
    )
    first = await evaluator.evaluate_release(agent, release, NOW - timedelta(minutes=20), False)
    assert first is not None
    stored = await meta.get_release("agent-1", "cand")
    assert stored is not None
    second = await evaluator.evaluate_release(agent, stored, NOW, False)
    assert second is not None
    assert second.state is VerdictState.PASS
    assert "format_failure_rate" not in second.metrics["items"]


async def test_no_baseline_pending(settings: Settings) -> None:
    event, meta = InMemoryEventStore(), InMemoryMetaStore()
    await _seed(meta, event, 0.0)
    agent = await meta.get_agent("agent-1")
    assert agent is not None
    base = await meta.get_release("agent-1", "base")
    assert base is not None
    evaluator = Evaluator(
        event, meta, _settings(settings), InlinePool(), lambda: NOW, [], asyncio.Lock()
    )
    early = base.first_seen + timedelta(hours=2)
    result = await evaluator.evaluate_release(agent, base, early, False)
    assert result is not None
    assert result.state is VerdictState.PENDING
    assert result.reason is ReasonCode.no_baseline
    _ = Release
