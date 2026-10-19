from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from prometheus_client import REGISTRY

from apgar.config import Settings
from apgar.domain.enums import ReasonCode, Source, VerdictState
from apgar.domain.models import TurnRow
from apgar.storage.memory import InMemoryEventStore, InMemoryMetaStore
from apgar.telemetry import build_payload, log_startup, turns_per_day_magnitude
from apgar.worker.jobs.telemetry import TelemetryJob
from tests.factories import make_agent, make_release

_NOW = datetime(2026, 10, 8, 9, 30, tzinfo=UTC)
_ENDPOINT = "https://telemetry.test/v1/report"


@pytest.mark.parametrize(
    ("turns", "magnitude"),
    [(0, 0), (9, 0), (10, 1), (999, 2), (1000, 3)],
)
def test_magnitude_rule(turns: int, magnitude: int) -> None:
    assert turns_per_day_magnitude(turns) == magnitude


def _turn(agent_id: str, index: int) -> TurnRow:
    start = _NOW - timedelta(hours=1)
    return TurnRow(
        agent_id=agent_id,
        release="rel",
        start_ts=start,
        turn_id=f"{agent_id}-{index}",
        trace_id=f"{index:032x}",
        root_span_id="ab" * 8,
        source_id="otlp",
        environment="production",
        prompt_version="",
        session_id=f"s-{index}",
        session_inferred=False,
        surface="web",
        end_ts=start + timedelta(seconds=1),
        latency_ms=10,
        llm_calls=1,
        llm_errors=0,
        tool_calls=0,
        tool_errors=0,
        tool_retries=0,
        loop_flag=False,
        zero_tool_flag=True,
        input_tokens=1,
        output_tokens=1,
        output_chars=1,
        cost_usd=0.0,
        primary_response_model="gpt-4.1",
        response_models=["gpt-4.1"],
        format_ok=None,
        late=False,
        partial=False,
        source=Source.otlp,
        ingested_at=start,
        version=1,
    )


async def test_payload_fields_and_demo_exclusion(settings: Settings) -> None:
    event, meta = InMemoryEventStore(), InMemoryMetaStore()
    live = make_agent(_NOW, id="live", name="live-agent", is_demo=False)
    demo = make_agent(_NOW, id="demo", name="demo-agent", is_demo=True)
    await meta.upsert_agent(live)
    await meta.upsert_agent(demo)
    await meta.upsert_release(
        make_release(_NOW, agent_id=live.id, release="rel", state=VerdictState.PASS)
    )
    await meta.upsert_release(
        make_release(
            _NOW,
            agent_id=demo.id,
            release="rel",
            state=VerdictState.FAIL,
            reason=ReasonCode.confirmed,
        )
    )
    await event.upsert_turns([_turn(live.id, index) for index in range(10)])
    await event.upsert_turns([_turn(demo.id, 10_000 + index) for index in range(1000)])
    payload = await build_payload(meta, event, settings, _NOW)
    assert payload["schema"] == 1
    assert payload["version"] == "0.1.0"
    assert payload["agents_non_demo"] == 1
    assert payload["agents_demo"] == 1
    assert payload["turns_per_day_magnitude"] == 1
    assert payload["verdict_counts"] == {
        "PASS": 1,
        "FAIL": 0,
        "INCONCLUSIVE": 0,
        "PENDING": 0,
    }
    assert payload["sent_at"] == "2026-10-08T09:30:00.000Z"
    uuid.UUID(str(payload["instance_id"]))


async def test_instance_id_is_stable(settings: Settings) -> None:
    event, meta = InMemoryEventStore(), InMemoryMetaStore()
    first = await build_payload(meta, event, settings, _NOW)
    second = await build_payload(meta, event, settings, _NOW)
    assert first["instance_id"] == second["instance_id"]
    assert await meta.get_setting("telemetry.instance_id") == first["instance_id"]


def _client(handler: httpx.MockTransport) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=handler)


def _sending(settings: Settings) -> Settings:
    # The shipped default endpoint is not a URL yet, so tests that send pick their own.
    return settings.model_copy(update={"telemetry_endpoint": _ENDPOINT})


async def test_disabled_by_env(settings: Settings) -> None:
    event, meta = InMemoryEventStore(), InMemoryMetaStore()
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(204)

    disabled = settings.model_copy(update={"telemetry": 0})
    job = TelemetryJob(event, meta, disabled, client=_client(httpx.MockTransport(handler)))
    await job.run(_NOW)
    assert calls == 0
    assert await meta.get_setting("telemetry.last_attempt_date") is None


async def test_disabled_by_setting(settings: Settings) -> None:
    event, meta = InMemoryEventStore(), InMemoryMetaStore()
    await meta.set_setting("telemetry.enabled", "0", _NOW)
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(204)

    job = TelemetryJob(event, meta, settings, client=_client(httpx.MockTransport(handler)))
    await job.run(_NOW)
    assert calls == 0


async def test_once_per_day(settings: Settings) -> None:
    event, meta = InMemoryEventStore(), InMemoryMetaStore()
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        assert str(request.url) == _ENDPOINT
        return httpx.Response(204)

    job = TelemetryJob(
        event, meta, _sending(settings), client=_client(httpx.MockTransport(handler))
    )
    await job.run(_NOW)
    await job.run(_NOW)
    assert calls == 1
    assert await meta.get_setting("telemetry.last_sent_date") == "2026-10-08"


async def test_failure_is_not_retried_the_same_day(settings: Settings) -> None:
    event, meta = InMemoryEventStore(), InMemoryMetaStore()
    calls = 0
    before = REGISTRY.get_sample_value("apgar_telemetry_attempts_total", {"result": "error"}) or 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(500)

    job = TelemetryJob(
        event, meta, _sending(settings), client=_client(httpx.MockTransport(handler))
    )
    await job.run(_NOW)
    await job.run(_NOW + timedelta(hours=1))
    assert calls == 1
    assert await meta.get_setting("telemetry.last_sent_date") is None
    assert await meta.get_setting("telemetry.last_attempt_date") == "2026-10-08"
    after = REGISTRY.get_sample_value("apgar_telemetry_attempts_total", {"result": "error"}) or 0
    assert after == before + 1


def test_startup_logs_disabled_once(settings: Settings, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="apgar.telemetry")
    log_startup(settings.model_copy(update={"telemetry": 0}))
    assert caplog.text.count("telemetry disabled") == 1
