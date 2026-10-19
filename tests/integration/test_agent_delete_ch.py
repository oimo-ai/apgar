from __future__ import annotations

from datetime import timedelta

import httpx
import pytest
from httpx import ASGITransport

from apgar.api.app import create_app
from apgar.storage.clickhouse.event_store import ClickHouseEventStore
from apgar.worker.jobs.retention import RetentionJob
from tests.factories import make_agent, make_release
from tests.support import FIXTURE_NOW, ChDatabase, Clock, make_span, make_turn

pytestmark = pytest.mark.integration


async def _scalar(event: ClickHouseEventStore, sql: str) -> int:
    result = await event.client.query(sql)
    return int(result.result_rows[0][0])


async def test_delete_hides_agent_and_retention_purges(ch_database: ChDatabase) -> None:
    settings, event, meta = ch_database
    app = create_app(settings, event, meta, Clock(FIXTURE_NOW))
    agent = make_agent(FIXTURE_NOW, name="billing-copilot")
    await meta.upsert_agent(agent)
    await event.upsert_turns([make_turn(FIXTURE_NOW, agent_id=agent.id)])
    await meta.upsert_release(make_release(FIXTURE_NOW, agent_id=agent.id))
    headers = {"Authorization": f"Bearer {settings.admin_token}"}
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        deleted = await client.delete("/api/v1/agents/billing-copilot", headers=headers)
        missing = await client.get("/api/v1/agents/billing-copilot", headers=headers)
    assert deleted.status_code == 204
    assert missing.status_code == 404
    hinted = make_span(FIXTURE_NOW, agent_hint=agent.id, trace_id="ab" * 16, span_id="cd" * 8)
    linked = make_span(FIXTURE_NOW, source_id="src", trace_id="11" * 16, span_id="ee" * 8)
    other = make_span(FIXTURE_NOW, agent_hint="someone-else", trace_id="ff" * 16, span_id="12" * 8)
    await event.insert_spans([hinted, linked, other])
    await RetentionJob(event, meta, event.client, settings.late_span_days).run(
        FIXTURE_NOW + timedelta(seconds=1)
    )
    assert await _scalar(event, "SELECT count() FROM turns FINAL") == 0
    assert await _scalar(event, "SELECT count() FROM releases FINAL") == 0
    hinted_left = await event.client.query(
        "SELECT count() FROM spans FINAL WHERE agent_hint = {a:String}",
        parameters={"a": agent.id},
    )
    linked_left = await event.client.query(
        "SELECT count() FROM spans FINAL WHERE span_id = {s:String}",
        parameters={"s": linked.span_id},
    )
    other_left = await event.client.query(
        "SELECT count() FROM spans FINAL WHERE agent_hint = {a:String}",
        parameters={"a": "someone-else"},
    )
    assert int(hinted_left.result_rows[0][0]) == 0
    assert int(linked_left.result_rows[0][0]) == 0
    assert int(other_left.result_rows[0][0]) == 1
    result = await event.client.query(
        "SELECT is_deleted FROM agents WHERE id = {id:String} ORDER BY updated_at DESC LIMIT 1",
        parameters={"id": agent.id},
    )
    assert int(result.result_rows[0][0]) == 1
