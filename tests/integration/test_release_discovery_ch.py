from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta
from typing import Any

import httpx
import pytest
from httpx import ASGITransport

from apgar.api.app import create_app
from apgar.assembly.assembler import Assembler
from apgar.domain.models import Agent, TurnRow
from apgar.domain.settings import ReleaseSettings
from apgar.normalize.normalizer import HmacKeys
from apgar.storage.clickhouse.event_store import ClickHouseEventStore
from apgar.worker.jobs.release_discovery import ReleaseDiscovery
from apgar.worker.jobs.rollup import RollupJob
from tests.factories import make_agent
from tests.support import FIXTURE_NOW, ChDatabase, Clock, load_fixture

pytestmark = pytest.mark.integration


async def _rows(event: ClickHouseEventStore, sql: str) -> list[dict[str, Any]]:
    result = await event.client.query(sql)
    names = [str(name) for name in result.column_names]
    return [{names[i]: row[i] for i in range(len(names))} for row in result.result_rows]


def _with_release(name: str, release: str, trace_id: str) -> bytes:
    payload = json.loads(load_fixture(name))
    spans = payload["resourceSpans"][0]["scopeSpans"][0]["spans"]
    found = False
    for span in spans:
        span["traceId"] = trace_id
        for attr in span.get("attributes", []):
            if attr["key"] == "gen_ai.agent.version":
                attr["value"]["stringValue"] = release
                found = True
    if not found:
        spans[0].setdefault("attributes", []).append(
            {"key": "gen_ai.agent.version", "value": {"stringValue": release}}
        )
    return json.dumps(payload).encode()


async def test_discovery_registers_production_releases_and_rollup(ch_database: ChDatabase) -> None:
    settings, event, meta = ch_database
    clock = Clock(FIXTURE_NOW)
    agent = make_agent(FIXTURE_NOW, environment="production", release_settings=ReleaseSettings())
    await meta.upsert_agent(agent)
    app = create_app(settings, event, meta, clock)
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        token = await client.post(
            "/api/v1/ingest-tokens",
            headers={"Authorization": f"Bearer {settings.admin_token}"},
            json={"name": "dev"},
        )
        headers = {
            "Authorization": f"Bearer {token.json()['token']}",
            "Content-Type": "application/json",
        }
        basic = await client.post(
            "/v1/traces", content=load_fixture("genai_basic.json"), headers=headers
        )
        assert basic.status_code == 200
        second = _with_release("genai_basic.json", "c3d4e5f", "3" * 32)
        posted = await client.post("/v1/traces", content=second, headers=headers)
        assert posted.status_code == 200
        staging = _with_release("env_staging.json", "stagingrel", "c" * 32)
        staged = await client.post("/v1/traces", content=staging, headers=headers)
        assert staged.status_code == 200
    lock = asyncio.Lock()
    discovery = ReleaseDiscovery(meta, lock)

    async def on_turn(turn: TurnRow, found: Agent, now: datetime) -> None:
        await discovery.on_turn_assembled(turn, found, now)

    assembler = Assembler(
        event,
        meta,
        settings,
        HmacKeys.from_settings(settings),
        clock,
        on_turn_assembled=on_turn,
    )
    await assembler.run_once(FIXTURE_NOW + timedelta(seconds=61))
    releases = await _rows(event, "SELECT release FROM releases FINAL ORDER BY release")
    names = {str(row["release"]) for row in releases}
    assert "a1b2c3d" in names
    assert "c3d4e5f" in names
    assert "stagingrel" not in names
    await RollupJob(event, meta, lock).run(FIXTURE_NOW + timedelta(seconds=62))
    rolled = await _rows(
        event,
        "SELECT release, turn_count, last_seen IS NOT NULL AS has_last "
        "FROM releases FINAL WHERE release = 'a1b2c3d'",
    )
    assert int(rolled[0]["turn_count"]) >= 1
    assert int(rolled[0]["has_last"]) == 1
