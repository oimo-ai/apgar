from __future__ import annotations

import json
import logging
import platform
import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from prometheus_client import REGISTRY

from apgar import __version__
from apgar.config import Settings
from apgar.domain.enums import (
    ConnectionStatus,
    ConnectionType,
    NotificationEvent,
    NotificationStatus,
    ReasonCode,
    ReleaseEventType,
    Source,
    VerdictState,
)
from apgar.domain.models import TurnRow
from apgar.domain.settings import VerdictSettings
from apgar.storage.memory import InMemoryEventStore, InMemoryMetaStore
from apgar.telemetry import (
    EVENT,
    POSTHOG_PROJECT_TOKEN,
    build_payload,
    hours_bucket,
    log_startup,
    turns_per_day_magnitude,
    untagged_share_bucket,
)
from apgar.worker.jobs.telemetry import TelemetryJob
from tests.factories import (
    make_agent,
    make_connection,
    make_evaluation,
    make_notification,
    make_release,
    make_release_event,
)

_NOW = datetime(2026, 10, 8, 9, 30, tzinfo=UTC)
_HOUR = timedelta(hours=1)


@pytest.mark.parametrize(
    ("turns", "magnitude"),
    [(0, 0), (9, 0), (10, 1), (999, 2), (1000, 3)],
)
def test_magnitude_rule(turns: int, magnitude: int) -> None:
    assert turns_per_day_magnitude(turns) == magnitude


@pytest.mark.parametrize(
    ("untagged", "turns", "bucket"),
    [
        (0, 0, None),
        (0, 10, "0%"),
        (1, 100, "<10%"),
        (10, 100, "10-49%"),
        (50, 100, "50-99%"),
        (99, 100, "50-99%"),
        (100, 100, "100%"),
    ],
)
def test_untagged_share_bucket(untagged: int, turns: int, bucket: str | None) -> None:
    assert untagged_share_bucket(untagged, turns) == bucket


@pytest.mark.parametrize(
    ("hours", "bucket"),
    [(0.5, "<2h"), (2, "2-6h"), (23.9, "6-24h"), (24, "24-48h"), (48, "48h+"), (100, "48h+")],
)
def test_hours_bucket(hours: float, bucket: str) -> None:
    assert hours_bucket(hours) == bucket


def _turn(agent_id: str, index: int, release: str = "rel") -> TurnRow:
    start = _NOW - _HOUR
    return TurnRow(
        agent_id=agent_id,
        release=release,
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


async def test_payload_envelope_and_demo_exclusion(settings: Settings) -> None:
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
    assert payload["api_key"] == POSTHOG_PROJECT_TOKEN
    assert payload["event"] == EVENT
    assert payload["timestamp"] == "2026-10-08T09:30:00.000Z"
    uuid.UUID(str(payload["distinct_id"]))
    properties = payload["properties"]
    assert isinstance(properties, dict)
    assert properties["$process_person_profile"] is False
    assert properties["$geoip_disable"] is True
    assert properties["schema"] == 2
    assert properties["version"] == __version__
    assert properties["os"] == platform.system().lower()
    assert properties["arch"] == platform.machine().lower()
    assert properties["agents_non_demo"] == 1
    assert properties["agents_demo"] == 1
    assert properties["turns_per_day_magnitude"] == 1
    assert properties["releases_pass"] == 1
    assert properties["releases_fail"] == 0
    assert properties["releases_inconclusive"] == 0
    assert properties["releases_pending"] == 0
    assert all(not isinstance(value, dict | list) for value in properties.values())
    json.dumps(payload)


async def test_payload_usage_outcome_and_onboarding_fields(settings: Settings) -> None:
    event, meta = InMemoryEventStore(), InMemoryMetaStore()
    otlp = make_agent(_NOW, id="otlp", name="otlp-agent")
    langfuse = make_agent(
        _NOW,
        id="langfuse",
        name="langfuse-agent",
        source=Source.langfuse,
        metric_settings={},
        verdict_settings=VerdictSettings(min_turns=100),
    )
    demo = make_agent(_NOW, id="demo", name="demo-agent", is_demo=True)
    for agent in (otlp, langfuse, demo):
        await meta.upsert_agent(agent)
    await meta.set_setting("telemetry.created_date", "2026-10-01", _NOW)
    await meta.upsert_connection(make_connection(_NOW, id="c-lf", status=ConnectionStatus.error))
    await meta.upsert_connection(
        make_connection(
            _NOW,
            id="c-slack",
            name="alerts",
            type=ConnectionType.slack,
            config={"webhook_url": "https://hooks.slack.com/services/x"},
            status=ConnectionStatus.ok,
        )
    )
    releases = [
        make_release(_NOW, agent_id=otlp.id, release="new", first_seen=_NOW - _HOUR),
        make_release(
            _NOW,
            agent_id=otlp.id,
            release="passed",
            first_seen=_NOW - 50 * _HOUR,
            state=VerdictState.PASS,
            reason=ReasonCode.confirmed,
            final=True,
            final_at=_NOW - 2 * _HOUR,
        ),
        make_release(
            _NOW,
            agent_id=otlp.id,
            release="failed",
            first_seen=_NOW - 60 * _HOUR,
            state=VerdictState.FAIL,
            reason=ReasonCode.confirmed,
            final=True,
            final_at=_NOW - _HOUR,
        ),
        make_release(
            _NOW,
            agent_id=langfuse.id,
            release="elapsed",
            first_seen=_NOW - 80 * _HOUR,
            state=VerdictState.INCONCLUSIVE,
            reason=ReasonCode.window_elapsed,
            final=True,
            final_at=_NOW - 3 * _HOUR,
        ),
        make_release(
            _NOW,
            agent_id=langfuse.id,
            release="old",
            first_seen=_NOW - 200 * _HOUR,
            state=VerdictState.PASS,
            reason=ReasonCode.confirmed,
            final=True,
            final_at=_NOW - 30 * _HOUR,
        ),
        make_release(
            _NOW,
            agent_id=demo.id,
            release="demo",
            first_seen=_NOW - _HOUR,
            state=VerdictState.FAIL,
            reason=ReasonCode.confirmed,
            final=True,
            final_at=_NOW - _HOUR,
        ),
    ]
    for release in releases:
        await meta.upsert_release(release)
    passed_at = _NOW - 50 * _HOUR
    failed_at = _NOW - 60 * _HOUR
    for evaluation in (
        make_evaluation(
            passed_at + _HOUR, agent_id=otlp.id, release="passed", state=VerdictState.INCONCLUSIVE
        ),
        make_evaluation(
            passed_at + 3 * _HOUR, agent_id=otlp.id, release="passed", state=VerdictState.PASS
        ),
        make_evaluation(
            passed_at + 9 * _HOUR, agent_id=otlp.id, release="passed", state=VerdictState.PASS
        ),
        make_evaluation(
            failed_at + 5 * _HOUR, agent_id=otlp.id, release="failed", state=VerdictState.FAIL
        ),
    ):
        await meta.append_evaluation(evaluation)
    for release_event in (
        make_release_event(_NOW - _HOUR, agent_id=otlp.id, release="new"),
        make_release_event(
            _NOW - 2 * _HOUR,
            agent_id=otlp.id,
            release="new",
            type=ReleaseEventType.expected_changes,
        ),
        make_release_event(
            _NOW - 30 * _HOUR, agent_id=otlp.id, release="failed", type=ReleaseEventType.stop
        ),
        make_release_event(_NOW - _HOUR, agent_id=demo.id, release="demo"),
    ):
        await meta.append_release_event(release_event)
    for index, (agent_id, kind, status, created_at) in enumerate(
        [
            (otlp.id, NotificationEvent.regression, NotificationStatus.sent, _NOW - _HOUR),
            (otlp.id, NotificationEvent.healthy, NotificationStatus.failed, _NOW - 2 * _HOUR),
            (otlp.id, NotificationEvent.ended, NotificationStatus.sent, _NOW - 30 * _HOUR),
            (demo.id, NotificationEvent.release_detected, NotificationStatus.sent, _NOW - _HOUR),
        ]
    ):
        await meta.upsert_notification(
            make_notification(
                created_at,
                id=f"n-{index}",
                agent_id=agent_id,
                idempotency_key=f"key-{index}",
                event=kind,
                status=status,
            )
        )
    tagged = [_turn(otlp.id, index) for index in range(8)]
    untagged = [_turn(otlp.id, 100 + index, release="untagged") for index in range(2)]
    await event.upsert_turns(tagged + untagged)

    payload = await build_payload(meta, event, settings, _NOW)
    properties = payload["properties"]
    assert isinstance(properties, dict)
    expected = {
        "install_age_days": 7,
        "agents_non_demo": 2,
        "agents_demo": 1,
        "agents_otlp": 1,
        "agents_langfuse": 1,
        "agents_custom_verdict": 1,
        "agents_custom_metrics": 1,
        "turns_per_day_magnitude": 1,
        "untagged_share": "10-49%",
        "agents_without_turns_24h": 1,
        "connections_langfuse": 1,
        "connections_slack": 1,
        "connections_webhook": 0,
        "langfuse_connections_error": 1,
        "releases_pending": 1,
        "releases_inconclusive": 1,
        "releases_pass": 2,
        "releases_fail": 1,
        "releases_detected_24h": 1,
        "releases_ended_24h_pass": 1,
        "releases_ended_24h_fail": 1,
        "releases_ended_24h_window_elapsed": 1,
        "releases_ended_24h_stopped": 0,
        "releases_ended_24h_superseded": 0,
        "hours_to_verdict": "2-6h",
        "release_events_24h_manual_baseline": 1,
        "release_events_24h_expected_changes": 1,
        "release_events_24h_stop": 0,
        "notifications_24h_release_detected": 0,
        "notifications_24h_regression": 1,
        "notifications_24h_healthy": 1,
        "notifications_24h_ended": 0,
        "notifications_24h_pending": 0,
        "notifications_24h_sent": 1,
        "notifications_24h_failed": 1,
    }
    assert {key: properties[key] for key in expected} == expected


async def test_empty_instance_has_no_buckets(settings: Settings) -> None:
    event, meta = InMemoryEventStore(), InMemoryMetaStore()
    payload = await build_payload(meta, event, settings, _NOW)
    properties = payload["properties"]
    assert isinstance(properties, dict)
    assert properties["untagged_share"] is None
    assert properties["hours_to_verdict"] is None
    assert properties["install_age_days"] == 0


async def test_instance_id_is_stable(settings: Settings) -> None:
    event, meta = InMemoryEventStore(), InMemoryMetaStore()
    first = await build_payload(meta, event, settings, _NOW)
    second = await build_payload(meta, event, settings, _NOW + timedelta(days=3))
    assert first["distinct_id"] == second["distinct_id"]
    assert await meta.get_setting("telemetry.instance_id") == first["distinct_id"]
    assert await meta.get_setting("telemetry.created_date") == "2026-10-08"
    properties = second["properties"]
    assert isinstance(properties, dict)
    assert properties["install_age_days"] == 3


def _client(handler: httpx.MockTransport) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=handler)


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
    bodies: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == settings.telemetry_endpoint
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json={"status": "Ok"})

    job = TelemetryJob(event, meta, settings, client=_client(httpx.MockTransport(handler)))
    await job.run(_NOW)
    await job.run(_NOW)
    assert len(bodies) == 1
    assert bodies[0]["api_key"] == POSTHOG_PROJECT_TOKEN
    assert bodies[0]["event"] == EVENT
    assert bodies[0]["distinct_id"] == await meta.get_setting("telemetry.instance_id")
    assert await meta.get_setting("telemetry.last_sent_date") == "2026-10-08"


async def test_endpoint_setting_overrides_default(settings: Settings) -> None:
    event, meta = InMemoryEventStore(), InMemoryMetaStore()
    await meta.set_setting("telemetry.endpoint", "https://collector.invalid/i/v0/e/", _NOW)
    urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        urls.append(str(request.url))
        return httpx.Response(200)

    job = TelemetryJob(event, meta, settings, client=_client(httpx.MockTransport(handler)))
    await job.run(_NOW)
    assert urls == ["https://collector.invalid/i/v0/e/"]


async def test_failure_is_not_retried_the_same_day(settings: Settings) -> None:
    event, meta = InMemoryEventStore(), InMemoryMetaStore()
    calls = 0
    before = REGISTRY.get_sample_value("apgar_telemetry_attempts_total", {"result": "error"}) or 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(500)

    job = TelemetryJob(event, meta, settings, client=_client(httpx.MockTransport(handler)))
    await job.run(_NOW)
    await job.run(_NOW + _HOUR)
    assert calls == 1
    assert await meta.get_setting("telemetry.last_sent_date") is None
    assert await meta.get_setting("telemetry.last_attempt_date") == "2026-10-08"
    after = REGISTRY.get_sample_value("apgar_telemetry_attempts_total", {"result": "error"}) or 0
    assert after == before + 1


def test_startup_logs_disabled_once(settings: Settings, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="apgar.telemetry")
    log_startup(settings.model_copy(update={"telemetry": 0}))
    assert caplog.text.count("telemetry disabled") == 1
