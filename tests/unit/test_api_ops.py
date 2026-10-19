from __future__ import annotations

from datetime import datetime, timedelta
from typing import cast

import httpx
from httpx import ASGITransport

from apgar import __version__
from apgar.api.app import create_app
from apgar.config import Settings
from apgar.storage.clickhouse.migrate import EXPECTED_SCHEMA_VERSION
from apgar.storage.interfaces import MetaStore
from apgar.storage.memory import InMemoryEventStore, InMemoryMetaStore
from apgar.worker.heartbeat import write
from tests.factories import make_agent


async def test_healthz_ok(app_client: httpx.AsyncClient) -> None:
    response = await app_client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_readyz_ok_when_schema_matches(app_client: httpx.AsyncClient) -> None:
    response = await app_client.get("/readyz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "schema_version": EXPECTED_SCHEMA_VERSION}


async def test_readyz_503_when_store_raises(settings: Settings) -> None:
    class Boom:
        async def schema_version(self) -> int:
            raise RuntimeError("down")

    app = create_app(settings, InMemoryEventStore(), cast(MetaStore, Boom()))
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/readyz")
    assert response.status_code == 503
    assert response.json() == {"status": "unavailable", "reason": "storage_unavailable"}


async def test_readyz_503_on_schema_mismatch(settings: Settings) -> None:
    class Mismatch:
        async def schema_version(self) -> int:
            return 999

    app = create_app(settings, InMemoryEventStore(), cast(MetaStore, Mismatch()))
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/readyz")
    assert response.status_code == 503
    assert response.json() == {"status": "unavailable", "reason": "schema_mismatch"}


async def test_metrics_endpoint_text_format(app_client: httpx.AsyncClient) -> None:
    response = await app_client.get("/metrics")
    assert response.status_code == 200
    assert "text/plain" in response.headers["content-type"]
    assert "version=0.0.4" in response.headers["content-type"]
    assert response.text


async def test_status_shape(
    settings: Settings,
    mem_stores: tuple[InMemoryEventStore, InMemoryMetaStore],
    fixed_now: object,
) -> None:
    from datetime import datetime

    assert isinstance(fixed_now, datetime)
    event_store, meta = mem_stores
    clock = {"now": fixed_now}
    app = create_app(settings, event_store, meta, clock=lambda: clock["now"])
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        body = (await client.get("/api/v1/status")).json()
        assert body["version"] == __version__
        assert body["storage"] == "ok"
        assert body["schema_version"] == EXPECTED_SCHEMA_VERSION
        assert body["worker_heartbeat_age_seconds"] is None
        assert body["demo_agents"] == 0
        await meta.upsert_agent(make_agent(fixed_now, is_demo=True))
        await write(meta, "worker-1", fixed_now)
        clock["now"] = fixed_now + timedelta(seconds=4)
        updated = (await client.get("/api/v1/status")).json()
    assert updated["demo_agents"] == 1
    assert updated["worker_heartbeat_age_seconds"] == 4


async def test_openapi_served(app_client: httpx.AsyncClient) -> None:
    response = await app_client.get("/api/openapi.json")
    assert response.status_code == 200
    body = response.json()
    assert body["info"]["title"] == "Apgar"
    assert "/healthz" in body["paths"]


async def test_error_body_format_for_404(app_client: httpx.AsyncClient) -> None:
    response = await app_client.get("/api/v1/missing")
    assert response.status_code == 404
    body = response.json()
    assert body["error"]["code"] == "not_found"
    assert isinstance(body["error"]["message"], str)


def test_merge_metrics_keeps_worker_sample() -> None:
    from apgar.api.metrics import merge_metrics

    local = (
        b"# HELP apgar_assembly_lag_seconds Age\n"
        b"# TYPE apgar_assembly_lag_seconds gauge\n"
        b"apgar_assembly_lag_seconds 0.0\n"
        b'apgar_ingest_requests_total{source_id="s",status="200"} 1.0\n'
    )
    remote = (
        b"# HELP apgar_assembly_lag_seconds Age\n"
        b"# TYPE apgar_assembly_lag_seconds gauge\n"
        b"apgar_assembly_lag_seconds 12.0\n"
        b'apgar_turns_assembled_total{agent="billing-copilot"} 1.0\n'
    )
    text = merge_metrics(local, remote).decode()
    assert "apgar_assembly_lag_seconds 0.0" not in text
    assert "apgar_assembly_lag_seconds 12.0" in text
    assert "apgar_turns_assembled_total" in text
    assert "apgar_ingest_requests_total" in text


async def test_purge_resets_demo_agents(
    settings: Settings,
    mem_stores: tuple[InMemoryEventStore, InMemoryMetaStore],
    fixed_now: datetime,
) -> None:
    from apgar.demo.generator import purge

    event_store, meta_store = mem_stores
    await meta_store.upsert_agent(make_agent(fixed_now, is_demo=True))
    app = create_app(settings, event_store, meta_store, clock=lambda: fixed_now)
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        before = await client.get("/api/v1/status")
        assert before.json()["demo_agents"] == 1
        await purge(event_store, meta_store, fixed_now)
        after = await client.get("/api/v1/status")
    assert after.json()["demo_agents"] == 0
    assert await meta_store.list_agents() == []
