from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
import respx

from apgar.assembly.assembler import Assembler
from apgar.config import Settings
from apgar.connectors.langfuse.client import (
    LangfuseClient,
    LangfuseClientError,
    LangfuseServerError,
)
from apgar.connectors.langfuse.sync import LangfuseSync
from apgar.domain.enums import Source
from apgar.domain.models import Connection, SyncState
from apgar.domain.settings import AgentFilter, ReleaseSettings
from apgar.domain.time import to_iso
from apgar.ingest.pipeline import write_batch
from apgar.normalize.normalizer import normalize
from apgar.normalize.otlp import decode_request, iter_raw_spans
from apgar.storage.memory import InMemoryEventStore, InMemoryMetaStore
from apgar.worker.jobs.langfuse_sync import LangfuseSyncJob
from tests.factories import make_agent, make_connection
from tests.support import FIXTURE_NOW, keys_for, load_fixture
from tests.tools.fake_langfuse import select_observations

_HOST = "http://langfuse.test"
_OBS = _HOST + "/api/public/v2/observations"
_NOW = datetime(2026, 10, 8, 9, 30, tzinfo=UTC)


def _connection(now: datetime) -> Connection:
    return make_connection(
        now,
        id="conn-lf",
        name="lf",
        config={
            "host": _HOST,
            "public_key": "pk",
            "secret_key": "sk",
            "project_id": "proj-123",
            "fetch_content": True,
        },
    )


async def _sync_for(
    settings: Settings,
    meta: InMemoryMetaStore,
    event: InMemoryEventStore,
    connection: Connection,
    http: httpx.AsyncClient,
) -> LangfuseSync:
    await meta.upsert_connection(connection)
    return LangfuseSync(
        connection,
        LangfuseClient(_HOST, "pk", "sk", http, lambda: _NOW, connection.name),
        event,
        meta,
        settings,
        keys_for(settings),
    )


async def test_window_arithmetic_first_run_and_subsequent(settings: Settings) -> None:
    event, meta = InMemoryEventStore(), InMemoryMetaStore()
    connection = _connection(_NOW)
    with respx.mock:
        respx.get(_OBS).mock(return_value=httpx.Response(200, json={"data": [], "meta": {}}))
        async with httpx.AsyncClient() as http:
            sync = await _sync_for(settings, meta, event, connection, http)
            first = await sync.run_cycle(_NOW)
            state = await meta.get_sync_state(connection.id)
            second = await sync.run_cycle(_NOW + timedelta(minutes=10))
    assert first.skipped is False
    assert first.window_end == _NOW - timedelta(minutes=2)
    assert first.window_start == _NOW - timedelta(hours=24) - timedelta(minutes=30)
    assert state is not None
    assert state.watermark == first.window_end
    assert second.window_start == first.window_end - timedelta(minutes=30)
    assert second.window_end == _NOW + timedelta(minutes=10) - timedelta(minutes=2)


async def test_watermark_advances_only_after_full_pagination(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _sleep(_delay: float) -> None:
        return None

    monkeypatch.setattr(asyncio, "sleep", _sleep)
    page = json.loads(Path("tests/fixtures/langfuse/roots_page1.json").read_text())
    event, meta = InMemoryEventStore(), InMemoryMetaStore()
    connection = _connection(_NOW)
    agent = make_agent(
        _NOW,
        id="agent-1",
        name="lf-billing",
        source=Source.langfuse,
        langfuse_connection_id=connection.id,
        filter=AgentFilter(trace_name="billing-copilot"),
    )

    def _respond(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("cursor") == "c1":
            return httpx.Response(500, text="down")
        return httpx.Response(200, json=page)

    with respx.mock:
        respx.get(_OBS).mock(side_effect=_respond)
        async with httpx.AsyncClient() as http:
            sync = await _sync_for(settings, meta, event, connection, http)
            await meta.upsert_agent(agent)
            with pytest.raises(LangfuseServerError):
                await sync.run_cycle(_NOW)
    state = await meta.get_sync_state(connection.id)
    assert state is not None
    assert state.watermark is None
    assert state.in_progress is False
    assert "500" in state.last_error or "Server" in state.last_error or state.last_error


async def test_two_agents_one_project_routed_by_root(settings: Settings) -> None:
    event, meta = InMemoryEventStore(), InMemoryMetaStore()
    connection = _connection(_NOW)
    billing_page = json.loads(Path("tests/fixtures/langfuse/roots_page1.json").read_text())
    support_page = json.loads(Path("tests/fixtures/langfuse/roots_other_agent.json").read_text())
    billing = billing_page["data"][0]
    support = support_page["data"][0]
    first = make_agent(
        _NOW,
        id="agent-billing",
        name="lf-billing",
        source=Source.langfuse,
        langfuse_connection_id=connection.id,
        filter=AgentFilter(trace_name="billing-copilot"),
        created_at=_NOW,
    )
    second = make_agent(
        _NOW + timedelta(seconds=1),
        id="agent-support",
        name="lf-support",
        source=Source.langfuse,
        langfuse_connection_id=connection.id,
        filter=AgentFilter(trace_name="support-agent"),
        created_at=_NOW + timedelta(seconds=1),
    )

    def _respond(request: httpx.Request) -> httpx.Response:
        raw = request.url.params.get("filter", "")
        if "support-agent" in raw:
            data = [support]
        elif "billing-copilot" in raw:
            data = [billing]
        else:
            data = [billing, support]
        return httpx.Response(200, json={"data": data, "meta": {}})

    with respx.mock:
        respx.get(_OBS).mock(side_effect=_respond)
        async with httpx.AsyncClient() as http:
            sync = await _sync_for(settings, meta, event, connection, http)
            await meta.upsert_agent(first)
            await meta.upsert_agent(second)
            result = await sync.run_cycle(_NOW)
    assert result.traces == 2
    hints = {row.agent_hint for row in event._spans.values()}
    assert hints == {"agent-billing", "agent-support"}


async def test_overlapping_filters_first_agent_wins(settings: Settings) -> None:
    event, meta = InMemoryEventStore(), InMemoryMetaStore()
    connection = _connection(_NOW)
    root = json.loads(Path("tests/fixtures/langfuse/roots_page1.json").read_text())["data"][0]
    first = make_agent(
        _NOW,
        id="agent-first",
        name="first",
        source=Source.langfuse,
        langfuse_connection_id=connection.id,
        filter=AgentFilter(trace_name="billing-copilot"),
        created_at=_NOW,
    )
    second = make_agent(
        _NOW,
        id="agent-second",
        name="second",
        source=Source.langfuse,
        langfuse_connection_id=connection.id,
        filter=AgentFilter(tags=["prod"]),
        created_at=_NOW + timedelta(seconds=5),
    )
    with respx.mock:
        respx.get(_OBS).mock(return_value=httpx.Response(200, json={"data": [root], "meta": {}}))
        async with httpx.AsyncClient() as http:
            sync = await _sync_for(settings, meta, event, connection, http)
            await meta.upsert_agent(first)
            await meta.upsert_agent(second)
            result = await sync.run_cycle(_NOW)
    assert result.traces == 1
    assert {row.agent_hint for row in event._spans.values()} == {"agent-first"}


async def test_observations_become_turns(settings: Settings) -> None:
    event, meta = InMemoryEventStore(), InMemoryMetaStore()
    otlp_event = InMemoryEventStore()
    connection = _connection(FIXTURE_NOW)
    agent = make_agent(
        FIXTURE_NOW,
        source=Source.langfuse,
        langfuse_connection_id=connection.id,
        filter=AgentFilter(trace_name="billing-copilot"),
        release_settings=ReleaseSettings(),
    )
    root = {
        "id": "6767676767676767",
        "traceId": "77777777777777777777777777777777",
        "type": "SPAN",
        "name": "billing",
        "startTime": "2026-10-08T08:00:00.000Z",
        "endTime": "2026-10-08T08:00:02.000Z",
        "isRootObservation": True,
        "parentObservationId": "0000000000000001",
        "traceName": "billing-copilot",
        "release": "a1b2c3d",
        "sessionId": "s-lf",
        "environment": "production",
        "promptName": "billing",
        "promptVersion": 7,
    }
    generation = {
        "id": "6868686868686868",
        "traceId": root["traceId"],
        "type": "GENERATION",
        "name": "generation",
        "startTime": "2026-10-08T08:00:00.100Z",
        "endTime": "2026-10-08T08:00:01.000Z",
        "isRootObservation": False,
        "parentObservationId": root["id"],
        "model": "gpt-4.1",
        "usageDetails": {"input": 900, "output": 150},
        "costDetails": {"total": 0.003},
    }
    tool = {
        "id": "6969696969696969",
        "traceId": root["traceId"],
        "type": "TOOL",
        "name": "sql_query",
        "startTime": "2026-10-08T08:00:01.000Z",
        "endTime": "2026-10-08T08:00:01.300Z",
        "isRootObservation": False,
        "parentObservationId": root["id"],
        "input": '{"q": "select 1"}',
    }

    def _respond(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("isRootObservation") == "true":
            data = [root]
        else:
            data = [root, generation, tool]
        return httpx.Response(200, json={"data": data, "meta": {}})

    with respx.mock:
        respx.get(_OBS).mock(side_effect=_respond)
        async with httpx.AsyncClient() as http:
            sync = await _sync_for(settings, meta, event, connection, http)
            await meta.upsert_agent(agent)
            await sync.run_cycle(FIXTURE_NOW)
    await Assembler(event, meta, settings, keys_for(settings), lambda: FIXTURE_NOW).run_once(
        FIXTURE_NOW + timedelta(seconds=61)
    )
    rows = [
        normalize(
            raw,
            source_id="src",
            source=Source.otlp,
            agent_hint="",
            now=FIXTURE_NOW,
            late_days=settings.late_span_days,
            keys=keys_for(settings),
        )
        for raw in iter_raw_spans(
            decode_request(load_fixture("langfuse_otel_basic.json"), "application/json", None)
        )
        if raw.trace_id
    ]
    await write_batch(otlp_event, rows, FIXTURE_NOW)
    otlp_meta = InMemoryMetaStore()
    otlp_assembler = Assembler(
        otlp_event, otlp_meta, settings, keys_for(settings), lambda: FIXTURE_NOW
    )
    await otlp_assembler.run_once(FIXTURE_NOW + timedelta(seconds=61))
    lf = next(iter(event._turns.values()))
    otlp = next(iter(otlp_event._turns.values()))
    assert lf.llm_calls == otlp.llm_calls == 1
    assert lf.tool_calls == otlp.tool_calls == 1
    assert lf.release == otlp.release == "a1b2c3d"
    assert lf.session_id == otlp.session_id == "s-lf"
    assert lf.prompt_version == otlp.prompt_version == "billing@7"


async def test_late_arrival_inside_lookback_is_picked_up(settings: Settings) -> None:
    event, meta = InMemoryEventStore(), InMemoryMetaStore()
    connection = _connection(_NOW)
    agent = make_agent(
        _NOW,
        source=Source.langfuse,
        langfuse_connection_id=connection.id,
        filter=AgentFilter(trace_name="billing-copilot"),
    )
    late = {
        "id": "aaaaaaaaaaaaaaaa",
        "traceId": "11111111111111111111111111111111",
        "type": "SPAN",
        "name": "billing",
        "startTime": to_iso(_NOW - timedelta(minutes=1)),
        "isRootObservation": True,
        "traceName": "billing-copilot",
        "release": "a1b2c3d",
        "environment": "production",
    }

    def _respond(request: httpx.Request) -> httpx.Response:
        page, cursor = select_observations([late], list(request.url.params.multi_items()))
        return httpx.Response(200, json={"data": page, "meta": {"cursor": cursor}})

    with respx.mock:
        respx.get(_OBS).mock(side_effect=_respond)
        async with httpx.AsyncClient() as http:
            sync = await _sync_for(settings, meta, event, connection, http)
            await meta.upsert_agent(agent)
            first = await sync.run_cycle(_NOW)
            second = await sync.run_cycle(_NOW + timedelta(minutes=10))
    assert first.traces == 0
    assert second.traces == 1
    assert second.spans_written == 1


async def test_skip_when_window_empty(settings: Settings) -> None:
    event, meta = InMemoryEventStore(), InMemoryMetaStore()
    connection = _connection(_NOW)
    await meta.upsert_connection(connection)
    await meta.upsert_sync_state(
        SyncState(
            connection_id=connection.id,
            watermark=_NOW + timedelta(hours=1),
            last_success_at=None,
            last_error="",
            last_error_at=None,
            lag_seconds=None,
            in_progress=False,
            updated_at=_NOW,
        )
    )
    async with httpx.AsyncClient() as http:
        sync = await _sync_for(settings, meta, event, connection, http)
        result = await sync.run_cycle(_NOW)
    assert result.skipped is True
    state = await meta.get_sync_state(connection.id)
    assert state is not None
    assert state.watermark == _NOW + timedelta(hours=1)


async def test_in_progress_guard(settings: Settings) -> None:
    event, meta = InMemoryEventStore(), InMemoryMetaStore()
    connection = _connection(_NOW)
    await meta.upsert_connection(connection)
    await meta.upsert_sync_state(
        SyncState(
            connection_id=connection.id,
            watermark=_NOW - timedelta(hours=1),
            last_success_at=_NOW - timedelta(hours=1),
            last_error="",
            last_error_at=None,
            lag_seconds=120,
            in_progress=True,
            updated_at=_NOW,
        )
    )
    async with httpx.AsyncClient() as http:
        sync = await _sync_for(settings, meta, event, connection, http)
        result = await sync.run_cycle(_NOW + timedelta(minutes=1))
    assert result.skipped is True
    state = await meta.get_sync_state(connection.id)
    assert state is not None
    assert state.watermark == _NOW - timedelta(hours=1)
    assert state.in_progress is True


async def test_malformed_observation_does_not_stall_the_window(settings: Settings) -> None:
    event, meta = InMemoryEventStore(), InMemoryMetaStore()
    connection = _connection(FIXTURE_NOW)
    agent = make_agent(
        FIXTURE_NOW,
        source=Source.langfuse,
        langfuse_connection_id=connection.id,
        filter=AgentFilter(trace_name="billing-copilot"),
        release_settings=ReleaseSettings(),
    )
    root = {
        "id": "6767676767676767",
        "traceId": "77777777777777777777777777777777",
        "type": "SPAN",
        "name": "billing",
        "startTime": "2026-10-08T08:00:00.000Z",
        "endTime": "2026-10-08T08:00:02.000Z",
        "traceName": "billing-copilot",
    }
    broken = {"id": "6868686868686868", "traceId": root["traceId"], "type": "EVENT", "name": "nope"}

    def _respond(request: httpx.Request) -> httpx.Response:
        root_only = request.url.params.get("isRootObservation") == "true"
        data = [root] if root_only else [root, broken]
        return httpx.Response(200, json={"data": data, "meta": {}})

    with respx.mock:
        respx.get(_OBS).mock(side_effect=_respond)
        async with httpx.AsyncClient() as http:
            sync = await _sync_for(settings, meta, event, connection, http)
            await meta.upsert_agent(agent)
            result = await sync.run_cycle(FIXTURE_NOW)
    assert result.spans_written == 1
    assert len(event._spans) == 1
    state = await meta.get_sync_state(connection.id)
    assert state is not None
    assert state.watermark == result.window_end


async def test_failed_connection_does_not_skip_the_next(settings: Settings) -> None:
    event, meta = InMemoryEventStore(), InMemoryMetaStore()
    bad = make_connection(
        FIXTURE_NOW,
        id="conn-bad",
        name="a-bad",
        config={"host": "http://bad.test", "public_key": "pk", "secret_key": "sk"},
    )
    good = make_connection(
        FIXTURE_NOW,
        id="conn-good",
        name="b-good",
        config={
            "host": "http://good.test",
            "public_key": "pk",
            "secret_key": "sk",
            "project_id": "proj",
            "fetch_content": True,
        },
    )
    await meta.upsert_connection(bad)
    await meta.upsert_connection(good)
    job = LangfuseSyncJob(event, meta, settings, keys_for(settings))
    try:
        with respx.mock:
            respx.get("http://bad.test/api/public/projects").mock(return_value=httpx.Response(401))
            with pytest.raises(LangfuseClientError):
                await job.run(FIXTURE_NOW)
    finally:
        await job.aclose()
    bad_state = await meta.get_sync_state(bad.id)
    good_state = await meta.get_sync_state(good.id)
    assert bad_state is not None
    assert bad_state.watermark is None
    assert bad_state.last_error
    assert good_state is not None
    assert good_state.watermark is not None


def _instrumented_trace(index: int) -> list[dict[str, object]]:
    trace_id = f"{index + 1:032x}"
    start = FIXTURE_NOW - timedelta(minutes=50) + timedelta(minutes=index)
    question = f"why was invoice {index % 4} charged twice"
    answer = json.dumps({"answer": f"refund issued for invoice {index % 4}"})
    root = {
        "id": f"{index + 1:016x}",
        "traceId": trace_id,
        "type": "SPAN",
        "name": "billing",
        "startTime": to_iso(start),
        "endTime": to_iso(start + timedelta(seconds=2)),
        "isRootObservation": True,
        "traceName": "billing-copilot",
        "release": "a1b2c3d",
        "sessionId": f"s-{index // 5}",
        "environment": "production",
        "input": question,
        "output": answer,
    }
    generation = {
        "id": f"{index + 1:08x}{'a' * 8}",
        "traceId": trace_id,
        "type": "GENERATION",
        "name": "generation",
        "startTime": to_iso(start + timedelta(milliseconds=100)),
        "endTime": to_iso(start + timedelta(seconds=1)),
        "parentObservationId": root["id"],
        "model": "gpt-4.1",
        "usageDetails": {"input": 900, "output": 150},
        "input": [{"role": "user", "content": question}],
        "output": {"role": "assistant", "content": answer},
    }
    tool = {
        "id": f"{index + 1:08x}{'b' * 8}",
        "traceId": trace_id,
        "type": "TOOL",
        "name": "sql_query",
        "startTime": to_iso(start + timedelta(seconds=1)),
        "endTime": to_iso(start + timedelta(milliseconds=1300)),
        "parentObservationId": root["id"],
        "input": json.dumps({"invoice": index % 4}),
    }
    return [root, generation, tool]


async def test_instrumented_agent_gets_behavior_metrics(settings: Settings) -> None:
    from apgar.domain.enums import MetricId, OutputFormat
    from apgar.domain.settings import effective_metric_settings
    from apgar.storage.types import ArmQuery
    from apgar.verdict.applicability import assess
    from apgar.verdict.metrics import specs_for

    event, meta = InMemoryEventStore(), InMemoryMetaStore()
    connection = _connection(FIXTURE_NOW)
    agent = make_agent(
        FIXTURE_NOW,
        source=Source.langfuse,
        langfuse_connection_id=connection.id,
        filter=AgentFilter(trace_name="billing-copilot"),
        output_format=OutputFormat.json,
        release_settings=ReleaseSettings(),
    )
    traces = [_instrumented_trace(index) for index in range(40)]
    requested: list[str] = []

    def _respond(request: httpx.Request) -> httpx.Response:
        requested.append(request.url.params.get("fields", ""))
        roots = request.url.params.get("isRootObservation") == "true"
        data = [obs for trace in traces for obs in (trace[:1] if roots else trace)]
        return httpx.Response(200, json={"data": data, "meta": {}})

    with respx.mock:
        respx.get(_OBS).mock(side_effect=_respond)
        async with httpx.AsyncClient() as http:
            sync = await _sync_for(settings, meta, event, connection, http)
            await meta.upsert_agent(agent)
            await sync.run_cycle(FIXTURE_NOW)
    await Assembler(event, meta, settings, keys_for(settings), lambda: FIXTURE_NOW).run_once(
        FIXTURE_NOW + timedelta(seconds=61)
    )
    assert any("io" in fields.split(",") for fields in requested)
    arm = await event.load_arm(
        ArmQuery(
            agent.id,
            "a1b2c3d",
            FIXTURE_NOW - timedelta(hours=2),
            FIXTURE_NOW,
            "",
            False,
            None,
            None,
            FIXTURE_NOW,
            False,
        )
    )
    assert len(arm.turns) == 40
    specs = {spec.id: spec for spec in specs_for(effective_metric_settings({}))}
    for metric_id in (
        MetricId.tool_retry_rate,
        MetricId.loop_rate,
        MetricId.format_failure_rate,
    ):
        decision = assess(specs[metric_id], arm.turns, arm.tool_calls, arm.turns, arm.tool_calls)
        assert decision.applicable, (metric_id, decision.na_reason)
