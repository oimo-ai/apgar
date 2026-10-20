from __future__ import annotations

import gzip
import json
from dataclasses import replace
from datetime import datetime, timedelta

import httpx
import pytest
from httpx import ASGITransport
from prometheus_client import REGISTRY

from apgar.api.app import create_app
from apgar.api.metrics import INGEST_SPANS_ACCEPTED
from apgar.assembly.assembler import Assembler
from apgar.config import Settings
from apgar.domain.models import Agent, TurnRow
from apgar.domain.settings import ReleaseSettings
from apgar.ingest.pipeline import write_batch
from apgar.security import generate_token, hash_token
from apgar.storage.memory import InMemoryEventStore, InMemoryMetaStore
from tests.factories import make_agent, make_ingest_token
from tests.support import FIXTURE_NOW, Clock, MemStores, keys_for, load_fixture, make_span


def _sample(name: str, labels: dict[str, str]) -> float:
    value = REGISTRY.get_sample_value(name, labels)
    return 0.0 if value is None else value


async def _client(
    settings: Settings,
    stores: tuple[InMemoryEventStore, InMemoryMetaStore],
    clock: Clock,
) -> httpx.AsyncClient:
    app = create_app(settings, stores[0], stores[1], clock)
    return httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _token(meta: InMemoryMetaStore, now: datetime, **overrides: object) -> str:
    plaintext = generate_token("apg_ing_")
    token = make_ingest_token(
        now,
        token_hash=hash_token(plaintext),
        token_prefix=plaintext[:12],
        **overrides,
    )
    await meta.upsert_ingest_token(token)
    return plaintext


async def test_missing_token_401(settings: Settings, mem_stores: MemStores) -> None:
    clock = Clock(FIXTURE_NOW)
    async with await _client(settings, mem_stores, clock) as client:
        response = await client.post(
            "/v1/traces",
            content=load_fixture("genai_basic.json"),
            headers={"content-type": "application/json"},
        )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


async def test_revoked_token_401(settings: Settings, mem_stores: MemStores) -> None:
    event, meta = mem_stores
    clock = Clock(FIXTURE_NOW)
    plaintext = await _token(meta, FIXTURE_NOW, revoked_at=FIXTURE_NOW)
    async with await _client(settings, (event, meta), clock) as client:
        response = await client.post(
            "/v1/traces",
            content=load_fixture("genai_basic.json"),
            headers={"authorization": f"Bearer {plaintext}", "content-type": "application/json"},
        )
    assert response.status_code == 401


async def test_json_request_200_and_rows_written(settings: Settings, mem_stores: MemStores) -> None:
    event, meta = mem_stores
    plaintext = await _token(meta, FIXTURE_NOW)
    async with await _client(settings, mem_stores, Clock(FIXTURE_NOW)) as client:
        response = await client.post(
            "/v1/traces",
            content=load_fixture("genai_basic.json"),
            headers={"authorization": f"Bearer {plaintext}", "content-type": "application/json"},
        )
    assert response.status_code == 200
    assert response.json() == {}
    spans = await event.spans_of_trace(
        (await meta.list_ingest_tokens())[0].id,
        "1" * 32,
    )
    assert len(spans) == 3


async def test_protobuf_request_200(settings: Settings, mem_stores: MemStores) -> None:
    from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
        ExportTraceServiceRequest,
        ExportTraceServiceResponse,
    )

    event, meta = mem_stores
    plaintext = await _token(meta, FIXTURE_NOW)
    request = ExportTraceServiceRequest()
    span = request.resource_spans.add().scope_spans.add().spans.add()
    span.trace_id = bytes.fromhex("12" * 16)
    span.span_id = bytes.fromhex("ab" * 8)
    span.name = "proto"
    span.start_time_unix_nano = 1_759_914_000_000_000_000
    span.end_time_unix_nano = 1_759_914_001_000_000_000
    async with await _client(settings, mem_stores, Clock(FIXTURE_NOW)) as client:
        response = await client.post(
            "/v1/traces",
            content=request.SerializeToString(),
            headers={
                "authorization": f"Bearer {plaintext}",
                "content-type": "application/x-protobuf",
            },
        )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/x-protobuf")
    ExportTraceServiceResponse.FromString(response.content)
    assert await event.spans_of_trace((await meta.list_ingest_tokens())[0].id, "12" * 16)


async def test_gzip_request_200(settings: Settings, mem_stores: MemStores) -> None:
    import gzip

    event, meta = mem_stores
    plaintext = await _token(meta, FIXTURE_NOW)
    async with await _client(settings, mem_stores, Clock(FIXTURE_NOW)) as client:
        response = await client.post(
            "/v1/traces",
            content=gzip.compress(load_fixture("genai_basic.json")),
            headers={
                "authorization": f"Bearer {plaintext}",
                "content-type": "application/json",
                "content-encoding": "gzip",
            },
        )
    assert response.status_code == 200
    assert len(await event.spans_of_trace((await meta.list_ingest_tokens())[0].id, "1" * 32)) == 3


async def test_body_too_large_413(settings: Settings, mem_stores: MemStores) -> None:
    limited = settings.model_copy(update={"max_body_bytes": 32})
    plaintext = await _token(mem_stores[1], FIXTURE_NOW)
    async with await _client(limited, mem_stores, Clock(FIXTURE_NOW)) as client:
        response = await client.post(
            "/v1/traces",
            content=b"x" * 64,
            headers={"authorization": f"Bearer {plaintext}", "content-type": "application/json"},
        )
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "payload_too_large"


async def test_unsupported_media_415(settings: Settings, mem_stores: MemStores) -> None:
    plaintext = await _token(mem_stores[1], FIXTURE_NOW)
    async with await _client(settings, mem_stores, Clock(FIXTURE_NOW)) as client:
        response = await client.post(
            "/v1/traces",
            content=b"{}",
            headers={"authorization": f"Bearer {plaintext}", "content-type": "text/plain"},
        )
    assert response.status_code == 415
    assert response.json()["error"]["code"] == "unsupported_media_type"


async def test_malformed_400(settings: Settings, mem_stores: MemStores) -> None:
    plaintext = await _token(mem_stores[1], FIXTURE_NOW)
    async with await _client(settings, mem_stores, Clock(FIXTURE_NOW)) as client:
        response = await client.post(
            "/v1/traces",
            content=b"not-json",
            headers={"authorization": f"Bearer {plaintext}", "content-type": "application/json"},
        )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "malformed_payload"


async def test_storage_failure_503_with_retry_after(
    settings: Settings, mem_stores: MemStores
) -> None:
    _event, meta = mem_stores

    class Boom(InMemoryEventStore):
        async def insert_spans(self, rows: object) -> None:
            raise RuntimeError("clickhouse down")

    plaintext = await _token(meta, FIXTURE_NOW)
    async with await _client(settings, (Boom(), meta), Clock(FIXTURE_NOW)) as client:
        response = await client.post(
            "/v1/traces",
            content=load_fixture("genai_basic.json"),
            headers={"authorization": f"Bearer {plaintext}", "content-type": "application/json"},
        )
    assert response.status_code == 503
    assert response.headers["retry-after"] == "5"
    assert response.json()["error"]["code"] == "storage_unavailable"


async def test_token_lookup_failure_503_with_retry_after(settings: Settings) -> None:
    class BoomMeta(InMemoryMetaStore):
        async def get_ingest_token_by_hash(self, token_hash: str) -> None:
            del token_hash
            raise RuntimeError("clickhouse down")

    meta = BoomMeta()
    plaintext = await _token(meta, FIXTURE_NOW)
    app = create_app(settings, InMemoryEventStore(), meta, Clock(FIXTURE_NOW))
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/v1/traces",
            content=load_fixture("genai_basic.json"),
            headers={"authorization": f"Bearer {plaintext}", "content-type": "application/json"},
        )
    assert response.status_code == 503
    assert response.headers["retry-after"] == "5"
    assert response.json()["error"]["code"] == "storage_unavailable"


async def test_trace_state_carries_assembler_fields(
    settings: Settings, mem_stores: MemStores
) -> None:
    event, meta = mem_stores
    plaintext = await _token(meta, FIXTURE_NOW)
    token = (await meta.list_ingest_tokens())[0]
    from apgar.domain.models import TraceStateRow

    await event.upsert_trace_state(
        [
            TraceStateRow(
                source_id=token.id,
                trace_id="1" * 32,
                first_span_at=FIXTURE_NOW - timedelta(minutes=5),
                last_span_at=FIXTURE_NOW - timedelta(minutes=5),
                span_count=1,
                has_root=True,
                agent_id="agent-1",
                root_span_id="rootspanrootspan",
                release="kept",
                start_ts=FIXTURE_NOW - timedelta(minutes=5),
                assembled_at=FIXTURE_NOW - timedelta(minutes=4),
                assembled_version=2,
                content_hash="abc",
                updated_at=FIXTURE_NOW - timedelta(minutes=4),
            )
        ]
    )
    async with await _client(settings, mem_stores, Clock(FIXTURE_NOW)) as client:
        response = await client.post(
            "/v1/traces",
            content=load_fixture("genai_basic.json"),
            headers={"authorization": f"Bearer {plaintext}", "content-type": "application/json"},
        )
    assert response.status_code == 200
    state = (await event.read_trace_state([(token.id, "1" * 32)]))[(token.id, "1" * 32)]
    assert state.agent_id == "agent-1"
    assert state.root_span_id == "rootspanrootspan"
    assert state.release == "kept"
    assert state.assembled_version == 2
    assert state.content_hash == "abc"
    assert state.span_count == 4
    assert state.has_root is True
    assert state.first_span_at == FIXTURE_NOW - timedelta(minutes=5)


async def test_has_root_set(settings: Settings, mem_stores: MemStores) -> None:
    event, meta = mem_stores
    plaintext = await _token(meta, FIXTURE_NOW)
    async with await _client(settings, mem_stores, Clock(FIXTURE_NOW)) as client:
        await client.post(
            "/v1/traces",
            content=load_fixture("genai_basic.json"),
            headers={"authorization": f"Bearer {plaintext}", "content-type": "application/json"},
        )
        await client.post(
            "/v1/traces",
            content=load_fixture("partial_no_root.json"),
            headers={"authorization": f"Bearer {plaintext}", "content-type": "application/json"},
        )
    token = (await meta.list_ingest_tokens())[0]
    rooted = (await event.read_trace_state([(token.id, "1" * 32)]))[(token.id, "1" * 32)]
    partial = (await event.read_trace_state([(token.id, "a" * 32)]))[(token.id, "a" * 32)]
    assert rooted.has_root is True
    assert partial.has_root is False


async def test_counters_incremented(settings: Settings, mem_stores: MemStores) -> None:
    _event, meta = mem_stores
    plaintext = await _token(meta, FIXTURE_NOW)
    token_id = (await meta.list_ingest_tokens())[0].id
    before = _sample("apgar_ingest_spans_accepted_total", {"source_id": token_id})
    async with await _client(settings, mem_stores, Clock(FIXTURE_NOW)) as client:
        response = await client.post(
            "/v1/traces",
            content=load_fixture("genai_basic.json"),
            headers={"authorization": f"Bearer {plaintext}", "content-type": "application/json"},
        )
        metrics = await client.get("/metrics")
    assert response.status_code == 200
    assert _sample("apgar_ingest_spans_accepted_total", {"source_id": token_id}) == before + 3
    assert "apgar_ingest_spans_accepted_total" in metrics.text
    assert INGEST_SPANS_ACCEPTED.labels(source_id=token_id)


async def test_token_cache_refreshes_after_60s(settings: Settings, mem_stores: MemStores) -> None:
    event, meta = mem_stores
    clock = Clock(FIXTURE_NOW)
    plaintext = await _token(meta, FIXTURE_NOW)
    headers = {"authorization": f"Bearer {plaintext}", "content-type": "application/json"}
    async with await _client(settings, mem_stores, clock) as client:
        first = await client.post(
            "/v1/traces", content=load_fixture("untagged.json"), headers=headers
        )
        assert first.status_code == 200
        token = (await meta.list_ingest_tokens())[0]
        await meta.upsert_ingest_token(
            replace(token, revoked_at=FIXTURE_NOW, updated_at=FIXTURE_NOW + timedelta(seconds=1))
        )
        cached = await client.post(
            "/v1/traces",
            content=load_fixture("untagged.json"),
            headers=headers,
        )
        assert cached.status_code == 200
        clock.now = FIXTURE_NOW + timedelta(seconds=61)
        refreshed = await client.post(
            "/v1/traces",
            content=load_fixture("untagged.json"),
            headers=headers,
        )
    assert refreshed.status_code == 401
    assert event


async def test_repeat_span_ids_do_not_refresh_quiet_clock(mem_stores: MemStores) -> None:
    event, _meta = mem_stores
    first = make_span(FIXTURE_NOW, trace_id="ab" * 16, span_id="cd" * 8, parent_span_id="")
    await write_batch(event, [first], FIXTURE_NOW)
    later = FIXTURE_NOW + timedelta(minutes=5)
    await write_batch(event, [first], later)
    state = (await event.read_trace_state([(first.source_id, first.trace_id)]))[
        (first.source_id, first.trace_id)
    ]
    assert state.last_span_at == FIXTURE_NOW
    assert state.span_count == 1
    extra = make_span(
        later, trace_id=first.trace_id, span_id="ee" * 8, parent_span_id=first.span_id
    )
    await write_batch(event, [extra], later)
    state = (await event.read_trace_state([(first.source_id, first.trace_id)]))[
        (first.source_id, first.trace_id)
    ]
    assert state.last_span_at == later
    assert state.span_count == 2


async def test_changed_span_content_refreshes_quiet_clock(mem_stores: MemStores) -> None:
    event, _meta = mem_stores
    first = make_span(FIXTURE_NOW, trace_id="ab" * 16, span_id="cd" * 8, parent_span_id="")
    await write_batch(event, [first], FIXTURE_NOW)
    later = FIXTURE_NOW + timedelta(minutes=5)
    updated = make_span(
        later,
        trace_id=first.trace_id,
        span_id=first.span_id,
        parent_span_id="",
        end_ts=later,
        cost_usd=1.5,
        ingested_at=later,
    )
    await write_batch(event, [updated], later)
    state = (await event.read_trace_state([(first.source_id, first.trace_id)]))[
        (first.source_id, first.trace_id)
    ]
    assert state.last_span_at == later
    assert state.span_count == 1


def _turn_body(trace_id: str, span: dict[str, str], resource: dict[str, str]) -> bytes:
    def pairs(values: dict[str, str]) -> list[dict[str, object]]:
        return [{"key": key, "value": {"stringValue": value}} for key, value in values.items()]

    start = int((FIXTURE_NOW - timedelta(seconds=5)).timestamp()) * 1_000_000_000
    root = {
        "traceId": trace_id,
        "spanId": "d" * 16,
        "name": "invoke_agent billing-copilot",
        "startTimeUnixNano": str(start),
        "endTimeUnixNano": str(start + 1_000_000_000),
        "attributes": pairs({"gen_ai.operation.name": "invoke_agent", **span}),
    }
    document = {
        "resourceSpans": [
            {"resource": {"attributes": pairs(resource)}, "scopeSpans": [{"spans": [root]}]}
        ]
    }
    return json.dumps(document).encode()


async def _assembled(settings: Settings, stores: MemStores, trace_id: str) -> TurnRow:
    event, meta = stores
    assembler = Assembler(event, meta, settings, keys_for(settings), lambda: FIXTURE_NOW)
    await assembler.run_once(FIXTURE_NOW + timedelta(seconds=61))
    return event._turns_by_trace[trace_id]


async def _bound_token(meta: InMemoryMetaStore, agent: Agent) -> dict[str, str]:
    await meta.upsert_agent(agent)
    plaintext = await _token(meta, FIXTURE_NOW, agent_id=agent.id)
    return {"authorization": f"Bearer {plaintext}", "content-type": "application/json"}


async def test_release_and_environment_fall_back_to_resource(
    settings: Settings, mem_stores: MemStores
) -> None:
    _event, meta = mem_stores
    headers = await _bound_token(meta, make_agent(FIXTURE_NOW, release_settings=ReleaseSettings()))
    body = _turn_body(
        "c" * 32, {}, {"gen_ai.agent.version": "r-resource", "apgar.environment": "staging"}
    )
    async with await _client(settings, mem_stores, Clock(FIXTURE_NOW)) as client:
        response = await client.post("/v1/traces", content=body, headers=headers)
    assert response.status_code == 200
    turn = await _assembled(settings, mem_stores, "c" * 32)
    assert (turn.release, turn.environment) == ("r-resource", "staging")


async def test_span_release_wins_over_resource(settings: Settings, mem_stores: MemStores) -> None:
    _event, meta = mem_stores
    headers = await _bound_token(meta, make_agent(FIXTURE_NOW, release_settings=ReleaseSettings()))
    body = _turn_body("c" * 32, {"apgar.release": "r-span"}, {"gen_ai.agent.version": "r-res"})
    async with await _client(settings, mem_stores, Clock(FIXTURE_NOW)) as client:
        await client.post("/v1/traces", content=body, headers=headers)
    assert (await _assembled(settings, mem_stores, "c" * 32)).release == "r-span"


async def test_custom_release_attribute_kept_right_after_agent_save(
    settings: Settings, mem_stores: MemStores, admin_headers: dict[str, str]
) -> None:
    _event, meta = mem_stores
    plaintext = await _token(meta, FIXTURE_NOW)
    headers = {"authorization": f"Bearer {plaintext}", "content-type": "application/json"}
    named = {"gen_ai.agent.name": "billing-copilot"}
    async with await _client(settings, mem_stores, Clock(FIXTURE_NOW)) as client:
        warm = await client.post(
            "/v1/traces", content=_turn_body("e" * 32, named, {}), headers=headers
        )
        assert warm.status_code == 200
        created = await client.post(
            "/api/v1/agents",
            headers=admin_headers,
            json={"name": "billing-copilot", "source": "otlp", "release": {"from": "app.release"}},
        )
        assert created.status_code == 201
        span_body = _turn_body("c" * 32, {**named, "app.release": "canary"}, {})
        resource_body = _turn_body("f" * 32, named, {"app.release": "from-resource"})
        for body in (span_body, resource_body):
            response = await client.post("/v1/traces", content=body, headers=headers)
            assert response.status_code == 200
    assert (await _assembled(settings, mem_stores, "c" * 32)).release == "canary"
    assert (await _assembled(settings, mem_stores, "f" * 32)).release == "from-resource"


async def test_agent_listing_failure_503(settings: Settings) -> None:
    class BoomMeta(InMemoryMetaStore):
        async def list_agents(
            self, include_demo: bool = True, include_deleted: bool = False
        ) -> list[Agent]:
            del include_demo, include_deleted
            raise RuntimeError("clickhouse down")

    meta = BoomMeta()
    plaintext = await _token(meta, FIXTURE_NOW)
    app = create_app(settings, InMemoryEventStore(), meta, Clock(FIXTURE_NOW))
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/v1/traces",
            content=load_fixture("genai_basic.json"),
            headers={"authorization": f"Bearer {plaintext}", "content-type": "application/json"},
        )
    assert response.status_code == 503
    assert response.headers["retry-after"] == "5"


@pytest.mark.parametrize(
    ("body", "encoding"),
    [
        (b"\xff", ""),
        (bytes.fromhex("1f8b0800000000000003ff000000000000000000"), "gzip"),
    ],
    ids=["invalid-utf8", "corrupt-deflate"],
)
async def test_malformed_encoding_returns_400(
    settings: Settings, mem_stores: MemStores, body: bytes, encoding: str
) -> None:
    plaintext = await _token(mem_stores[1], FIXTURE_NOW)
    async with await _client(settings, mem_stores, Clock(FIXTURE_NOW)) as client:
        response = await client.post(
            "/v1/traces",
            content=body,
            headers={
                "authorization": f"Bearer {plaintext}",
                "content-type": "application/json",
                "content-encoding": encoding,
            },
        )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "malformed_payload"


@pytest.mark.parametrize("over_limit", [False, True])
@pytest.mark.parametrize("media", ["application/json", "application/x-protobuf"])
async def test_gzip_expanded_body_limit(
    settings: Settings, mem_stores: MemStores, over_limit: bool, media: str
) -> None:
    from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest

    limit = 1024
    if media == "application/json":
        body = b" " * (limit - 2) + b"{}"
        extra = b" "
    else:
        request = ExportTraceServiceRequest()
        request.resource_spans.add().schema_url = "x" * 1000
        body = request.SerializeToString()
        limit = len(body)
        extra = b"\x00"
    if over_limit:
        body += extra
    compressed = gzip.compress(body)
    assert len(compressed) < limit
    plaintext = await _token(mem_stores[1], FIXTURE_NOW)
    limited = settings.model_copy(update={"max_body_bytes": limit})
    async with await _client(limited, mem_stores, Clock(FIXTURE_NOW)) as client:
        response = await client.post(
            "/v1/traces",
            content=compressed,
            headers={
                "authorization": f"Bearer {plaintext}",
                "content-type": media,
                "content-encoding": "gzip",
            },
        )
    assert response.status_code == (413 if over_limit else 200)
    if over_limit:
        assert response.json()["error"]["code"] == "payload_too_large"


@pytest.mark.parametrize("media", ["application/json", "application/x-protobuf"])
@pytest.mark.parametrize("invalid", ["trace_id", "span_id", "parent_span_id"])
async def test_invalid_ids_drop_only_the_bad_span(
    settings: Settings, mem_stores: MemStores, media: str, invalid: str
) -> None:
    from google.protobuf.json_format import MessageToJson
    from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest

    request = ExportTraceServiceRequest()
    spans = request.resource_spans.add().scope_spans.add().spans
    for _ in range(2):
        span = spans.add()
        span.trace_id = bytes.fromhex("12" * 16)
        span.span_id = bytes.fromhex("ab" * 8)
        span.start_time_unix_nano = int(FIXTURE_NOW.timestamp()) * 1_000_000_000
    setattr(
        spans[0], invalid, b"\x00" * {"trace_id": 16, "span_id": 8, "parent_span_id": 2}[invalid]
    )
    body = (
        request.SerializeToString()
        if media == "application/x-protobuf"
        else MessageToJson(request).encode()
    )
    event, meta = mem_stores
    plaintext = await _token(meta, FIXTURE_NOW)
    token_id = (await meta.list_ingest_tokens())[0].id
    before = _sample(
        "apgar_ingest_spans_dropped_total", {"source_id": token_id, "reason": "invalid_ids"}
    )
    async with await _client(settings, mem_stores, Clock(FIXTURE_NOW)) as client:
        response = await client.post(
            "/v1/traces",
            content=body,
            headers={"authorization": f"Bearer {plaintext}", "content-type": media},
        )
    assert response.status_code == 200
    stored = await event.spans_of_trace(token_id, "12" * 16)
    assert len(stored) == 1
    assert stored[0].span_id == "ab" * 8
    state = (await event.read_trace_state([(token_id, "12" * 16)]))[(token_id, "12" * 16)]
    assert state.span_count == 1
    assert (
        _sample(
            "apgar_ingest_spans_dropped_total", {"source_id": token_id, "reason": "invalid_ids"}
        )
        == before + 1
    )
