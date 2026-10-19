from __future__ import annotations

from datetime import timedelta
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from httpx import ASGITransport

from apgar.api.app import create_app
from apgar.assembly.assembler import Assembler
from apgar.config import Settings
from apgar.ingest.pipeline import write_batch
from apgar.normalize.normalizer import HmacKeys
from apgar.storage.clickhouse.event_store import ClickHouseEventStore
from apgar.storage.interfaces import MetaStore
from tests.support import FIXTURE_NOW, ChDatabase, Clock, load_fixture, make_span

pytestmark = pytest.mark.integration


def _app(settings: Settings, event: ClickHouseEventStore, meta: MetaStore, clock: Clock) -> FastAPI:
    return create_app(settings, event, meta, clock)


async def _token(client: httpx.AsyncClient, admin: str) -> str:
    response = await client.post(
        "/api/v1/ingest-tokens",
        headers={"authorization": f"Bearer {admin}"},
        json={"name": "dev"},
    )
    assert response.status_code == 201
    token = response.json()["token"]
    if not isinstance(token, str):
        raise AssertionError("token must be a string")
    return token


async def _post(client: httpx.AsyncClient, token: str, name: str) -> httpx.Response:
    return await client.post(
        "/v1/traces",
        content=load_fixture(name),
        headers={"authorization": f"Bearer {token}", "content-type": "application/json"},
    )


def _assembler(
    settings: Settings, event: ClickHouseEventStore, meta: MetaStore, clock: Clock
) -> Assembler:
    return Assembler(event, meta, settings, HmacKeys.from_settings(settings), clock)


async def _rows(event: ClickHouseEventStore, sql: str) -> list[dict[str, Any]]:
    result = await event.client.query(sql)
    names = [str(name) for name in result.column_names]
    return [{names[i]: row[i] for i in range(len(names))} for row in result.result_rows]


async def test_end_to_end_basic(ch_database: ChDatabase) -> None:
    settings, event, meta = ch_database
    clock = Clock(FIXTURE_NOW)
    app = _app(settings, event, meta, clock)
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        token = await _token(client, settings.admin_token)
        response = await _post(client, token, "genai_basic.json")
    assert response.status_code == 200
    await _assembler(settings, event, meta, clock).run_once(FIXTURE_NOW + timedelta(seconds=61))
    rows = await _rows(event, "SELECT release, llm_calls, tool_calls, partial FROM turns FINAL")
    assert len(rows) == 1
    assert rows[0]["release"] == "a1b2c3d"
    assert int(rows[0]["llm_calls"]) == 1
    assert int(rows[0]["tool_calls"]) == 1
    assert int(rows[0]["partial"]) == 0
    tools = await _rows(event, "SELECT count() AS n FROM tool_calls FINAL")
    assert int(tools[0]["n"]) == 1


async def test_duplicate_delivery_no_metric_change(ch_database: ChDatabase) -> None:
    settings, event, meta = ch_database
    clock = Clock(FIXTURE_NOW)
    app = _app(settings, event, meta, clock)
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        token = await _token(client, settings.admin_token)
        assert (await _post(client, token, "genai_basic.json")).status_code == 200
        await _assembler(settings, event, meta, clock).run_once(FIXTURE_NOW + timedelta(seconds=61))
        clock.now = FIXTURE_NOW + timedelta(minutes=2)
        assert (await _post(client, token, "genai_basic.json")).status_code == 200
    await _assembler(settings, event, meta, clock).run_once(FIXTURE_NOW + timedelta(minutes=4))
    spans = await _rows(event, "SELECT count() AS n FROM spans FINAL")
    turns = await _rows(event, "SELECT count() AS n FROM turns FINAL")
    version = await _rows(event, "SELECT assembled_version FROM trace_state FINAL")
    assert int(spans[0]["n"]) == 3
    assert int(turns[0]["n"]) == 1
    assert int(version[0]["assembled_version"]) == 1


async def test_reassembly_bumps_version_keeps_key(ch_database: ChDatabase) -> None:
    settings, event, meta = ch_database
    clock = Clock(FIXTURE_NOW)
    app = _app(settings, event, meta, clock)
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        token = await _token(client, settings.admin_token)
        assert (await _post(client, token, "reassembly_part1.json")).status_code == 200
        await _assembler(settings, event, meta, clock).run_once(FIXTURE_NOW + timedelta(seconds=61))
        first = await _rows(event, "SELECT turn_id, start_ts, release, version FROM turns FINAL")
        clock.now = FIXTURE_NOW + timedelta(minutes=2)
        assert (await _post(client, token, "reassembly_part2.json")).status_code == 200
    await _assembler(settings, event, meta, clock).run_once(
        FIXTURE_NOW + timedelta(minutes=3, seconds=1)
    )
    again = await _rows(
        event,
        "SELECT turn_id, start_ts, release, version, tool_calls FROM turns FINAL",
    )
    tools = await _rows(event, "SELECT count() AS n FROM tool_calls FINAL")
    assert again[0]["turn_id"] == first[0]["turn_id"]
    assert again[0]["start_ts"] == first[0]["start_ts"]
    assert again[0]["release"] == first[0]["release"]
    assert int(again[0]["version"]) == 2
    assert int(again[0]["tool_calls"]) == 2
    assert int(tools[0]["n"]) == 2


async def test_partial_after_deadline(ch_database: ChDatabase) -> None:
    settings, event, meta = ch_database
    clock = Clock(FIXTURE_NOW)
    app = _app(settings, event, meta, clock)
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        token = await _token(client, settings.admin_token)
        assert (await _post(client, token, "partial_no_root.json")).status_code == 200
    assembler = _assembler(settings, event, meta, clock)
    assert await assembler.run_once(FIXTURE_NOW + timedelta(seconds=61)) == 0
    assert await assembler.run_once(FIXTURE_NOW + timedelta(seconds=601)) == 1
    rows = await _rows(event, "SELECT partial, root_span_id FROM turns FINAL")
    assert int(rows[0]["partial"]) == 1
    assert rows[0]["root_span_id"] == "9292929292929292"


async def test_late_span_flagged(ch_database: ChDatabase) -> None:
    settings, event, meta = ch_database
    clock = Clock(FIXTURE_NOW)
    app = _app(settings, event, meta, clock)
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        token = await _token(client, settings.admin_token)
        assert (await _post(client, token, "late_span.json")).status_code == 200
    await _assembler(settings, event, meta, clock).run_once(FIXTURE_NOW + timedelta(seconds=61))
    rows = await _rows(event, "SELECT late FROM turns FINAL")
    assert int(rows[0]["late"]) == 1


async def test_trace_state_ttl_follows_the_write(ch_database: ChDatabase) -> None:
    _settings, event, _meta = ch_database
    # The demo seed replays weeks of traffic, so first_span_at is far older than
    # APGAR_LATE_SPAN_DAYS. The row must still live until the assembler reads it.
    replayed = FIXTURE_NOW - timedelta(days=30)
    await write_batch(event, [make_span(replayed)], replayed)
    await event.client.command(
        "INSERT INTO trace_state (source_id, trace_id, first_span_at, last_span_at, updated_at, "
        "written_at) VALUES ('src', 'stale', now64(3), now64(3), now64(6), now() - INTERVAL 8 DAY)"
    )
    await event.client.command("OPTIMIZE TABLE trace_state FINAL")
    rows = await _rows(event, "SELECT trace_id FROM trace_state FINAL")
    assert [row["trace_id"] for row in rows] == ["11" * 16]
