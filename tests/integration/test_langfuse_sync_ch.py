from __future__ import annotations

from datetime import timedelta
from typing import Any

import httpx
import pytest
import respx

from apgar.assembly.assembler import Assembler
from apgar.connectors.langfuse.client import LangfuseClient
from apgar.connectors.langfuse.sync import LangfuseSync
from apgar.domain.enums import Source
from apgar.domain.settings import AgentFilter
from apgar.normalize.normalizer import HmacKeys
from apgar.storage.clickhouse.event_store import ClickHouseEventStore
from tests.factories import make_agent, make_connection
from tests.support import FIXTURE_NOW, ChDatabase

pytestmark = pytest.mark.integration
_HOST = "http://langfuse.test"


async def _count(event: ClickHouseEventStore, sql: str) -> list[dict[str, Any]]:
    result = await event.client.query(sql)
    names = [str(name) for name in result.column_names]
    return [{names[i]: row[i] for i in range(len(names))} for row in result.result_rows]


async def test_sync_assembles_langfuse_turns_once(ch_database: ChDatabase) -> None:
    settings, event, meta = ch_database
    connection = make_connection(
        FIXTURE_NOW,
        id="conn-lf",
        config={
            "host": _HOST,
            "public_key": "pk",
            "secret_key": "sk",
            "project_id": "proj-123",
            "fetch_content": True,
        },
    )
    agent = make_agent(
        FIXTURE_NOW,
        source=Source.langfuse,
        langfuse_connection_id=connection.id,
        filter=AgentFilter(trace_name="billing-copilot"),
    )
    await meta.upsert_connection(connection)
    await meta.upsert_agent(agent)
    root = {
        "id": "6767676767676767",
        "traceId": "77777777777777777777777777777777",
        "type": "SPAN",
        "name": "billing",
        "startTime": "2026-10-08T08:00:00.000Z",
        "endTime": "2026-10-08T08:00:02.000Z",
        "isRootObservation": True,
        "traceName": "billing-copilot",
        "release": "a1b2c3d",
        "sessionId": "s-lf",
        "environment": "production",
        "promptName": "billing",
        "promptVersion": 7,
    }
    child = {
        "id": "6868686868686868",
        "traceId": root["traceId"],
        "type": "GENERATION",
        "name": "generation",
        "startTime": "2026-10-08T08:00:00.100Z",
        "endTime": "2026-10-08T08:00:01.000Z",
        "isRootObservation": False,
        "parentObservationId": root["id"],
        "model": "gpt-4.1",
    }

    def _respond(request: httpx.Request) -> httpx.Response:
        data = [root] if request.url.params.get("isRootObservation") == "true" else [root, child]
        return httpx.Response(200, json={"data": data, "meta": {}})

    with respx.mock:
        respx.get(_HOST + "/api/public/v2/observations").mock(side_effect=_respond)
        async with httpx.AsyncClient() as http:
            sync = LangfuseSync(
                connection,
                LangfuseClient(_HOST, "pk", "sk", http, lambda: FIXTURE_NOW, "lf"),
                event,
                meta,
                settings,
                HmacKeys.from_settings(settings),
            )
            await sync.run_cycle(FIXTURE_NOW)
            assembler = Assembler(
                event, meta, settings, HmacKeys.from_settings(settings), lambda: FIXTURE_NOW
            )
            await assembler.run_once(FIXTURE_NOW + timedelta(seconds=61))
            await sync.run_cycle(FIXTURE_NOW + timedelta(minutes=10))
            await assembler.run_once(FIXTURE_NOW + timedelta(minutes=10, seconds=61))
    rows = await _count(
        event,
        "SELECT count() AS n, any(source) AS source FROM turns FINAL",
    )
    assert int(rows[0]["n"]) == 1
    assert rows[0]["source"] == "langfuse"
