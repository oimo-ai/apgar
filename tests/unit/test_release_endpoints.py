from __future__ import annotations

from datetime import datetime, timedelta

import httpx

from apgar.domain.enums import ReasonCode, VerdictState
from tests.factories import make_release
from tests.support import MemStores


async def _agent(app_client: httpx.AsyncClient, admin_headers: dict[str, str]) -> None:
    created = await app_client.post(
        "/api/v1/agents",
        headers=admin_headers,
        json={"name": "billing-copilot", "source": "otlp"},
    )
    assert created.status_code == 201


async def test_list_ordering_and_window(
    app_client: httpx.AsyncClient,
    admin_headers: dict[str, str],
    mem_stores: MemStores,
    fixed_now: datetime,
) -> None:
    await _agent(app_client, admin_headers)
    _event, meta = mem_stores
    agent = await meta.get_agent_by_name("billing-copilot")
    assert agent is not None
    older = make_release(
        fixed_now,
        agent_id=agent.id,
        release="a1b2c3d",
        first_seen=fixed_now,
        state=VerdictState.PENDING,
        reason=ReasonCode.no_baseline,
    )
    newer = make_release(
        fixed_now,
        agent_id=agent.id,
        release="rel-two",
        first_seen=fixed_now + timedelta(hours=2),
        state=VerdictState.PASS,
        final=True,
    )
    await meta.upsert_release(older)
    await meta.upsert_release(newer)
    listed = await app_client.get("/api/v1/agents/billing-copilot/releases", headers=admin_headers)
    body = listed.json()
    assert body["total"] == 2
    assert [item["release"] for item in body["items"]] == ["rel-two", "a1b2c3d"]
    assert body["items"][1]["max_window_end"].startswith("2026-10-11T")
