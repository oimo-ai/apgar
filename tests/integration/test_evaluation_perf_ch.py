from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from apgar.domain.enums import OutputFormat, ReasonCode, Source, SpanStatus
from apgar.domain.models import Agent, ToolCallRow, TurnRow
from apgar.domain.settings import ReleaseSettings, SurfaceMapping, VerdictSettings
from apgar.verdict.evaluate import Evaluator
from apgar.verdict.pool import InlinePool
from apgar.worker.jobs.release_discovery import new_release
from tests.support import ChDatabase

pytestmark = [pytest.mark.integration, pytest.mark.slow]

_NOW = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)


def _agent() -> Agent:
    return Agent(
        id="perf-agent",
        name="perf-agent",
        source=Source.otlp,
        langfuse_connection_id="",
        filter=None,
        environment="",
        surface_mapping=SurfaceMapping(),
        release_settings=ReleaseSettings(),
        metric_settings={},
        verdict_settings=VerdictSettings(min_turns=200, min_sessions=30, min_turns_slice=100),
        output_format=OutputFormat.text,
        slack_connection_id="",
        is_demo=False,
        created_at=_NOW,
        updated_at=_NOW,
        deleted_at=None,
    )


async def test_evaluation_under_60_seconds(ch_database: ChDatabase) -> None:
    settings, event, meta = ch_database
    tuned = settings.model_copy(update={"bootstrap_resamples": 10000, "bootstrap_chunk": 256})
    agent = _agent()
    await meta.upsert_agent(agent)
    base_start = _NOW - timedelta(days=5)
    cand_start = _NOW - timedelta(hours=48)
    await meta.upsert_release(
        new_release(agent.id, "base", base_start, ReasonCode.no_baseline, base_start)
    )
    await meta.upsert_release(
        new_release(agent.id, "cand", cand_start, ReasonCode.insufficient_sample, cand_start)
    )
    tools = ("sql_query", "get_invoice", "send_email", "search", "refund")
    surfaces = ("slack", "web", "telegram")
    models = ("gpt-4.1", "gpt-4.1-mini")
    for release_name, start in (("base", base_start), ("cand", cand_start)):
        turns: list[TurnRow] = []
        calls: list[ToolCallRow] = []
        for index in range(100_000):
            session = index % 10_000
            start_ts = start + timedelta(seconds=index % 86_400)
            turn_id = f"{release_name}-{index}"
            error = release_name == "cand" and index % 11 == 0
            turns.append(
                TurnRow(
                    agent_id=agent.id,
                    release=release_name,
                    start_ts=start_ts,
                    turn_id=turn_id,
                    trace_id=f"{index:032x}",
                    root_span_id="ab" * 8,
                    source_id="perf",
                    environment="production",
                    prompt_version="v1",
                    session_id=f"{release_name}-{session}",
                    session_inferred=False,
                    surface=surfaces[index % 3],
                    end_ts=start_ts + timedelta(milliseconds=1000),
                    latency_ms=1000 + (index % 50),
                    llm_calls=1,
                    llm_errors=0,
                    tool_calls=1,
                    tool_errors=1 if error else 0,
                    tool_retries=0,
                    loop_flag=False,
                    zero_tool_flag=False,
                    input_tokens=20,
                    output_tokens=100 + (index % 7),
                    output_chars=40,
                    cost_usd=0.01,
                    primary_response_model=models[index % 2],
                    response_models=[models[index % 2]],
                    format_ok=None,
                    late=False,
                    partial=False,
                    source=Source.otlp,
                    ingested_at=start_ts,
                    version=1,
                )
            )
            calls.append(
                ToolCallRow(
                    agent_id=agent.id,
                    release=release_name,
                    turn_start_ts=start_ts,
                    turn_id=turn_id,
                    tool_call_id=f"c-{turn_id}",
                    session_id=f"{release_name}-{session}",
                    tool_name=tools[index % 5],
                    call_start_ts=start_ts,
                    duration_ms=5,
                    status=SpanStatus.error if error else SpanStatus.ok,
                    error_type="ToolError" if error else "",
                    args_hash="h",
                    is_retry=False,
                    surface=surfaces[index % 3],
                    version=1,
                )
            )
            if len(turns) == 20_000:
                await event.upsert_turns(turns)
                await event.insert_tool_calls(calls)
                turns.clear()
                calls.clear()
        if turns:
            await event.upsert_turns(turns)
            await event.insert_tool_calls(calls)
    release = await meta.get_release(agent.id, "cand")
    assert release is not None
    evaluator = Evaluator(event, meta, tuned, InlinePool(), lambda: _NOW, [], asyncio.Lock())
    result = await evaluator.evaluate_release(agent, release, _NOW, False)
    assert result is not None
    print(f"evaluation duration_ms={result.duration_ms}")
    assert result.duration_ms < 60_000
