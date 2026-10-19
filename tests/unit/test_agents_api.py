from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest

from tests.factories import make_release, make_sync_state
from tests.support import MemStores, make_turn


async def _ids(app_client: httpx.AsyncClient, admin_headers: dict[str, str]) -> tuple[str, str]:
    langfuse = await app_client.post(
        "/api/v1/connections",
        headers=admin_headers,
        json={
            "name": "lf",
            "type": "langfuse",
            "config": {
                "host": "https://cloud.langfuse.com",
                "public_key": "pk",
                "secret_key": "sk-test",
            },
        },
    )
    slack = await app_client.post(
        "/api/v1/connections",
        headers=admin_headers,
        json={
            "name": "slack",
            "type": "slack",
            "config": {"webhook_url": "https://hooks.slack.com/services/abc"},
        },
    )
    return langfuse.json()["id"], slack.json()["id"]


async def test_create_otlp_and_langfuse(
    app_client: httpx.AsyncClient, admin_headers: dict[str, str]
) -> None:
    langfuse_id, slack_id = await _ids(app_client, admin_headers)
    otlp = await app_client.post(
        "/api/v1/agents",
        headers=admin_headers,
        json={"name": "billing-copilot", "source": "otlp"},
    )
    assert otlp.status_code == 201
    assert len(otlp.json()["effective_metrics"]) == 11
    assert otlp.json()["environment"] is None
    langfuse = await app_client.post(
        "/api/v1/agents",
        headers=admin_headers,
        json={
            "name": "lf-billing",
            "source": "langfuse",
            "langfuse_connection": langfuse_id,
            "filter": {"trace_name": "billing-copilot"},
            "environment": "production",
            "slack_connection": slack_id,
        },
    )
    assert langfuse.status_code == 201
    assert langfuse.json()["langfuse_connection"] == langfuse_id


@pytest.mark.parametrize(
    ("body", "fragment"),
    [
        ({"name": "Bad Name", "source": "otlp"}, "name"),
        ({"name": "lf-a", "source": "langfuse"}, "langfuse_connection"),
        (
            {"name": "lf-b", "source": "langfuse", "langfuse_connection": "missing"},
            "langfuse_connection",
        ),
        (
            {
                "name": "lf-c",
                "source": "langfuse",
                "langfuse_connection": "LF",
                "filter": {"environment": "production"},
            },
            "filter",
        ),
        (
            {"name": "otlp-a", "source": "otlp", "langfuse_connection": "LF"},
            "langfuse_connection",
        ),
        (
            {"name": "otlp-b", "source": "otlp", "filter": {"trace_name": "x"}},
            "filter",
        ),
        (
            {"name": "m-a", "source": "otlp", "metrics": {"nope": {"tolerance": 0.1}}},
            "unknown metric",
        ),
        (
            {"name": "m-b", "source": "otlp", "metrics": {"tool_error_rate": {"tolerance": 0}}},
            "tolerance",
        ),
        ({"name": "v-a", "source": "otlp", "verdict": {"alpha": 0.6}}, "alpha"),
        (
            {"name": "v-b", "source": "otlp", "verdict": {"min_turns_early": 20}},
            "min_turns_early",
        ),
        (
            {"name": "s-a", "source": "otlp", "slack_connection": "LF"},
            "slack_connection",
        ),
    ],
)
async def test_validation_rules(
    app_client: httpx.AsyncClient,
    admin_headers: dict[str, str],
    body: dict[str, object],
    fragment: str,
) -> None:
    langfuse_id, _slack = await _ids(app_client, admin_headers)
    payload = dict(body)
    if payload.get("langfuse_connection") == "LF":
        payload["langfuse_connection"] = langfuse_id
    if payload.get("slack_connection") == "LF":
        payload["slack_connection"] = langfuse_id
    response = await app_client.post("/api/v1/agents", headers=admin_headers, json=payload)
    assert response.status_code == 422
    assert fragment in response.text


async def test_duplicate_patch_and_delete(
    app_client: httpx.AsyncClient, admin_headers: dict[str, str]
) -> None:
    await app_client.post(
        "/api/v1/agents",
        headers=admin_headers,
        json={"name": "billing-copilot", "source": "otlp"},
    )
    duplicate = await app_client.post(
        "/api/v1/agents",
        headers=admin_headers,
        json={"name": "billing-copilot", "source": "otlp"},
    )
    assert duplicate.status_code == 409
    patched = await app_client.patch(
        "/api/v1/agents/billing-copilot",
        headers=admin_headers,
        json={"output_format": "json", "environment": "production"},
    )
    assert patched.status_code == 200
    assert patched.json()["output_format"] == "json"
    assert patched.json()["environment"] == "production"
    locked = await app_client.patch(
        "/api/v1/agents/billing-copilot",
        headers=admin_headers,
        json={"name": "other"},
    )
    assert locked.status_code == 422
    token = await app_client.post(
        "/api/v1/ingest-tokens",
        headers=admin_headers,
        json={"name": "bound", "agent": "billing-copilot"},
    )
    deleted = await app_client.delete("/api/v1/agents/billing-copilot", headers=admin_headers)
    assert deleted.status_code == 204
    missing = await app_client.get("/api/v1/agents/billing-copilot", headers=admin_headers)
    assert missing.status_code == 404
    listed = await app_client.get("/api/v1/ingest-tokens", headers=admin_headers)
    match = next(item for item in listed.json()["items"] if item["id"] == token.json()["id"])
    assert match["revoked_at"] is not None


async def test_read_model(
    app_client: httpx.AsyncClient, admin_headers: dict[str, str], mem_stores: MemStores
) -> None:
    langfuse_id, _slack = await _ids(app_client, admin_headers)
    created = await app_client.post(
        "/api/v1/agents",
        headers=admin_headers,
        json={
            "name": "lf-billing",
            "source": "langfuse",
            "langfuse_connection": langfuse_id,
            "filter": {"trace_name": "billing-copilot"},
        },
    )
    agent_id = created.json()["id"]
    event, meta = mem_stores
    now = datetime.now(UTC)
    turns = []
    for index in range(8):
        turns.append(
            make_turn(
                now,
                agent_id=agent_id,
                turn_id=f"t{index}",
                release="a1b2c3d",
                environment="production" if index % 2 == 0 else "staging",
            )
        )
    turns.append(make_turn(now, agent_id=agent_id, turn_id="untagged-1", release="untagged"))
    turns.append(make_turn(now, agent_id=agent_id, turn_id="untagged-2", release="untagged"))
    await event.upsert_turns(turns)
    await meta.upsert_release(
        make_release(now, agent_id=agent_id, release="a1b2c3d", first_seen=now)
    )
    await meta.upsert_sync_state(make_sync_state(now, connection_id=langfuse_id, last_error="boom"))
    body = (await app_client.get("/api/v1/agents/lf-billing", headers=admin_headers)).json()
    assert body["activity"]["turns_24h"] == 10
    assert body["activity"]["untagged_share_24h"] == pytest.approx(0.2)
    assert body["latest_release"]["release"] == "a1b2c3d"
    assert body["coverage"] is None
    assert body["latest_release"]["failing_metrics"] == []
    assert body["sync"]["status"] == "error"
    assert set(body["warnings"]) == {"untagged_share", "multiple_environments", "sync_error"}
