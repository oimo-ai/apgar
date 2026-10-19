from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import httpx
import respx

from apgar.config import Settings
from apgar.connectors.langfuse.client import LangfuseClient
from apgar.connectors.langfuse.sync import (
    LangfuseSync,
    batches,
    build_phase_one_params,
    build_phase_two_params,
    build_trace_params,
)
from apgar.domain.enums import Source
from apgar.domain.settings import AgentFilter, SurfaceMapping
from apgar.storage.memory import InMemoryEventStore, InMemoryMetaStore
from tests.factories import make_agent, make_connection
from tests.support import keys_for

_START = datetime(2026, 10, 7, 9, 0, tzinfo=UTC)
_END = datetime(2026, 10, 8, 9, 28, tzinfo=UTC)


def _params(agent_filter: AgentFilter) -> list[tuple[str, str]]:
    agent = make_agent(
        _START,
        filter=agent_filter,
        surface_mapping=SurfaceMapping(from_attribute="metadata.channel"),
    )
    return build_phase_one_params(agent, _START, _END)


def test_phase_one_parameters() -> None:
    params = _params(
        AgentFilter(
            trace_name="billing-copilot",
            tags=["prod"],
            metadata={"channel": "slack"},
            environment="production",
        )
    )
    found = dict(params)
    assert found["isRootObservation"] == "true"
    assert found["environment"] == "production"
    assert "channel" in found["expandMetadata"]
    clauses = json.loads(found["filter"])
    kinds = {(clause["column"], clause["operator"]) for clause in clauses}
    assert ("traceName", "=") in kinds
    assert ("tags", "all of") in kinds
    assert ("metadata", "=") in kinds
    assert ("environment", "any of") in kinds
    assert ("isRootObservation", "=") in kinds


def test_phase_two_batches_of_50() -> None:
    ids = [f"t{index:04d}" for index in range(51)]
    groups = batches(ids)
    assert len(groups) == 2
    assert len(groups[0]) == 50
    params = build_phase_two_params(groups[0], _START, _END, True)
    found = dict(params)
    assert found["fields"].endswith(",io")
    value = json.loads(found["filter"])[0]["value"]
    assert len(value) == 50
    trace = dict(build_trace_params("t0000", _START, _END, False))
    assert trace["traceId"] == "t0000"
    assert "filter" not in trace
    assert not trace["fields"].endswith(",io")


async def test_fallback_flag_after_400(settings: Settings) -> None:
    event, meta = InMemoryEventStore(), InMemoryMetaStore()
    connection = make_connection(
        _START,
        id="conn-lf",
        config={
            "host": "http://langfuse.test",
            "public_key": "pk",
            "secret_key": "sk",
            "project_id": "proj-123",
            "fetch_content": False,
        },
    )
    await meta.upsert_connection(connection)
    await meta.upsert_agent(
        make_agent(
            _START,
            source=Source.langfuse,
            langfuse_connection_id=connection.id,
            filter=AgentFilter(trace_name="billing-copilot"),
        )
    )
    root = {
        "id": "aaaaaaaaaaaaaaaa",
        "traceId": "11111111111111111111111111111111",
        "type": "SPAN",
        "name": "billing",
        "startTime": "2026-10-08T08:00:00.000Z",
        "isRootObservation": True,
        "traceName": "billing-copilot",
        "release": "a1b2c3d",
    }
    filters: list[str] = []

    def _respond(request: httpx.Request) -> httpx.Response:
        raw = request.url.params.get("filter", "")
        filters.append(raw)
        if "traceId" in raw and "any of" in raw:
            return httpx.Response(400, text="unsupported")
        return httpx.Response(200, json={"data": [root], "meta": {}})

    with respx.mock:
        respx.get("http://langfuse.test/api/public/v2/observations").mock(side_effect=_respond)
        async with httpx.AsyncClient() as http:
            sync = LangfuseSync(
                connection,
                LangfuseClient("http://langfuse.test", "pk", "sk", http, lambda: _END, "lf"),
                event,
                meta,
                settings,
                keys_for(settings),
            )
            await sync.run_cycle(_END)
            assert sync.any_of_supported is False
            filters.clear()
            await sync.run_cycle(_END + timedelta(minutes=10))
    assert not any("traceId" in item and "any of" in item for item in filters)
