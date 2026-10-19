from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import httpx

from apgar.domain.enums import ReasonCode, VerdictState
from apgar.domain.retention import TRACE_EXPIRED
from apgar.storage.memory import InMemoryMetaStore
from tests.factories import make_evaluation, make_release
from tests.support import MemStores

NOW = datetime(2026, 10, 8, 9, 30, tzinfo=UTC)


async def _agent(
    app_client: httpx.AsyncClient, admin_headers: dict[str, str], meta: InMemoryMetaStore
) -> str:
    created = await app_client.post(
        "/api/v1/agents",
        headers=admin_headers,
        json={"name": "billing-copilot", "source": "otlp"},
    )
    assert created.status_code == 201
    agent_id = str(created.json()["id"])
    await meta.upsert_release(
        make_release(
            NOW,
            agent_id=agent_id,
            release="fp-fail",
            first_seen=NOW,
            state=VerdictState.FAIL,
            reason=ReasonCode.confirmed,
            verdict_summary={"verdict": "FAIL", "ok": False, "reason": "confirmed"},
        )
    )
    await meta.upsert_release(
        make_release(
            NOW,
            agent_id=agent_id,
            release="fp-pending",
            first_seen=NOW - timedelta(hours=1),
            state=VerdictState.PENDING,
            reason=ReasonCode.no_baseline,
        )
    )
    return agent_id


async def test_detail_actions_and_summary(
    app_client: httpx.AsyncClient, admin_headers: dict[str, str], mem_stores: MemStores
) -> None:
    _events, meta = mem_stores
    await _agent(app_client, admin_headers, meta)
    detail = await app_client.get(
        "/api/v1/agents/billing-copilot/releases/fp-fail", headers=admin_headers
    )
    assert detail.status_code == 200
    body = detail.json()
    assert body["actions"] == {
        "baseline": {"enabled": True},
        "stop": {"enabled": True},
        "expected_changes": {"enabled": True},
    }
    assert body["user_state"]["stopped_at"] is None
    assert body["summary"]["verdict"] == "FAIL"
    pending = await app_client.get(
        "/api/v1/agents/billing-copilot/releases/fp-pending", headers=admin_headers
    )
    assert pending.json()["summary"]["verdict"] == "PENDING"
    assert pending.json()["summary"]["ok"] is None


async def test_demo_releases_report_no_next_check(
    app_client: httpx.AsyncClient, admin_headers: dict[str, str], mem_stores: MemStores
) -> None:
    _events, meta = mem_stores
    agent_id = await _agent(app_client, admin_headers, meta)
    url = "/api/v1/agents/billing-copilot/releases/fp-pending"
    live = await app_client.get(url, headers=admin_headers)
    assert live.json()["timing"]["next_check_at"] is not None
    agent = await meta.get_agent(agent_id)
    assert agent is not None
    await meta.upsert_agent(replace(agent, is_demo=True))
    demo = await app_client.get(url, headers=admin_headers)
    assert demo.json()["timing"]["next_check_at"] is None


async def test_release_events(
    app_client: httpx.AsyncClient, admin_headers: dict[str, str], mem_stores: MemStores
) -> None:
    _events, meta = mem_stores
    await _agent(app_client, admin_headers, meta)
    baseline = await app_client.post(
        "/api/v1/agents/billing-copilot/releases/fp-fail/baseline",
        headers=admin_headers,
        json={"release": "fp-pending"},
    )
    changes = await app_client.post(
        "/api/v1/agents/billing-copilot/releases/fp-fail/expected-changes",
        headers=admin_headers,
        json={"metrics": ["tool_error_rate"]},
    )
    stop = await app_client.post(
        "/api/v1/agents/billing-copilot/releases/fp-fail/stop", headers=admin_headers
    )
    assert baseline.status_code == 202
    assert changes.status_code == 202
    assert stop.status_code == 202
    events = await app_client.get(
        "/api/v1/agents/billing-copilot/releases/fp-fail/events", headers=admin_headers
    )
    items = events.json()["items"]
    assert [item["type"] for item in items] == [
        "manual_baseline",
        "expected_changes",
        "stop",
    ]
    detail = await app_client.get(
        "/api/v1/agents/billing-copilot/releases/fp-fail", headers=admin_headers
    )
    assert detail.json()["actions"]["stop"]["enabled"] is False
    assert detail.json()["user_state"]["stopped_at"] is not None
    again = await app_client.post(
        "/api/v1/agents/billing-copilot/releases/fp-fail/stop", headers=admin_headers
    )
    assert again.status_code == 400
    assert again.json()["error"]["message"] == "monitoring is already stopping"
    newer = await app_client.post(
        "/api/v1/agents/billing-copilot/releases/fp-pending/baseline",
        headers=admin_headers,
        json={"release": "fp-fail"},
    )
    assert newer.status_code == 400
    assert newer.json()["error"]["message"] == (
        "baseline release must have been seen before the candidate"
    )


async def test_stop_and_baseline_are_rejected_once_final(
    app_client: httpx.AsyncClient, admin_headers: dict[str, str], mem_stores: MemStores
) -> None:
    _events, meta = mem_stores
    agent_id = await _agent(app_client, admin_headers, meta)
    await meta.upsert_release(
        make_release(
            NOW,
            agent_id=agent_id,
            release="fp-ended",
            first_seen=NOW - timedelta(hours=80),
            state=VerdictState.INCONCLUSIVE,
            reason=ReasonCode.window_elapsed,
            final=True,
        )
    )
    stop = await app_client.post(
        "/api/v1/agents/billing-copilot/releases/fp-ended/stop",
        headers=admin_headers,
        json={"actor": "ada"},
    )
    assert stop.status_code == 400
    assert stop.json()["error"]["message"] == "monitoring has already ended"
    baseline = await app_client.post(
        "/api/v1/agents/billing-copilot/releases/fp-ended/baseline",
        headers=admin_headers,
        json={"release": "fp-pending"},
    )
    assert baseline.status_code == 400
    assert baseline.json()["error"]["message"] == "monitoring has already ended"
    assert await meta.release_events(agent_id, "fp-ended") == []
    detail = await app_client.get(
        "/api/v1/agents/billing-copilot/releases/fp-ended", headers=admin_headers
    )
    assert detail.json()["actions"]["baseline"]["enabled"] is False


async def test_expected_changes_rejected_after_trace_data_expires(
    app_client: httpx.AsyncClient, admin_headers: dict[str, str], mem_stores: MemStores
) -> None:
    _events, meta = mem_stores
    agent_id = await _agent(app_client, admin_headers, meta)
    expired_at = datetime.now(UTC) - timedelta(days=100)
    await meta.upsert_release(
        make_release(
            NOW,
            agent_id=agent_id,
            release="fp-old",
            first_seen=expired_at,
            state=VerdictState.FAIL,
            reason=ReasonCode.confirmed,
            final=True,
        )
    )
    changes = await app_client.post(
        "/api/v1/agents/billing-copilot/releases/fp-old/expected-changes",
        headers=admin_headers,
        json={"metrics": ["tool_error_rate"]},
    )
    assert changes.status_code == 400
    assert changes.json()["error"]["message"] == TRACE_EXPIRED
    assert await meta.release_events(agent_id, "fp-old") == []
    detail = await app_client.get(
        "/api/v1/agents/billing-copilot/releases/fp-old", headers=admin_headers
    )
    assert detail.json()["actions"]["expected_changes"]["enabled"] is False


async def test_evaluations_newest_first_without_slices(
    app_client: httpx.AsyncClient, admin_headers: dict[str, str], mem_stores: MemStores
) -> None:
    _events, meta = mem_stores
    agent_id = await _agent(app_client, admin_headers, meta)
    older = make_evaluation(
        NOW - timedelta(hours=2), agent_id=agent_id, release="fp-fail", seed="aaaa1111"
    )
    newer = make_evaluation(NOW, agent_id=agent_id, release="fp-fail", seed="bbbb2222")
    await meta.append_evaluation(older)
    await meta.append_evaluation(newer)
    listed = await app_client.get(
        "/api/v1/agents/billing-copilot/releases/fp-fail/evaluations", headers=admin_headers
    )
    items = listed.json()["items"]
    assert [item["seed"] for item in items] == ["bbbb2222", "aaaa1111"]
    assert "slices" not in items[0]
