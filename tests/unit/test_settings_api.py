from __future__ import annotations

import httpx
from httpx import ASGITransport

from apgar.api.app import create_app
from apgar.config import Settings
from apgar.storage.memory import InMemoryEventStore, InMemoryMetaStore


async def test_defaults(app_client: httpx.AsyncClient, admin_headers: dict[str, str]) -> None:
    response = await app_client.get("/api/v1/settings", headers=admin_headers)
    body = response.json()
    assert body["retention"] == {"trace_data_days": 90, "verdict_history_days": 400}
    assert body["appearance"]["default_theme"] == "system"
    assert body["telemetry"]["enabled"] is True
    assert body["telemetry"]["disabled_by_environment"] is False
    assert body["telemetry"]["last_sent_date"] is None
    preview = body["telemetry"]["payload_preview"]
    assert preview["agents_demo"] == 0
    assert preview["agents_non_demo"] == 0
    assert preview["schema"] == 1


async def test_patch_persists(app_client: httpx.AsyncClient, admin_headers: dict[str, str]) -> None:
    patched = await app_client.patch(
        "/api/v1/settings",
        headers=admin_headers,
        json={
            "retention": {"trace_data_days": 30},
            "telemetry": {"enabled": False},
            "appearance": {"default_theme": "dark"},
        },
    )
    assert patched.status_code == 200
    body = patched.json()
    assert body["retention"]["trace_data_days"] == 30
    assert body["retention"]["verdict_history_days"] == 400
    assert body["telemetry"]["enabled"] is False
    assert body["appearance"]["default_theme"] == "dark"
    again = await app_client.get("/api/v1/settings", headers=admin_headers)
    assert again.json()["retention"]["trace_data_days"] == 30


async def test_validation_bounds(
    app_client: httpx.AsyncClient, admin_headers: dict[str, str]
) -> None:
    low = await app_client.patch(
        "/api/v1/settings", headers=admin_headers, json={"retention": {"trace_data_days": 20}}
    )
    high = await app_client.patch(
        "/api/v1/settings", headers=admin_headers, json={"retention": {"trace_data_days": 3651}}
    )
    old_key = await app_client.patch(
        "/api/v1/settings", headers=admin_headers, json={"retention": {"spans_days": 90}}
    )
    theme = await app_client.patch(
        "/api/v1/settings",
        headers=admin_headers,
        json={"appearance": {"default_theme": "purple"}},
    )
    assert low.status_code == 422
    assert "must be in [21, 3650]" in low.json()["error"]["message"]
    assert "conversation history" in low.json()["error"]["message"]
    assert high.status_code == 422
    assert old_key.status_code == 422
    assert old_key.json()["error"]["message"] == "retention: unknown field spans_days"
    assert theme.status_code == 422


async def test_verdict_history_cannot_be_shorter_than_trace_data(
    app_client: httpx.AsyncClient, admin_headers: dict[str, str]
) -> None:
    stored = await app_client.patch(
        "/api/v1/settings",
        headers=admin_headers,
        json={"retention": {"verdict_history_days": 50}},
    )
    assert stored.status_code == 422
    assert "trace_data_days (90)" in stored.json()["error"]["message"]
    together = await app_client.patch(
        "/api/v1/settings",
        headers=admin_headers,
        json={"retention": {"trace_data_days": 40, "verdict_history_days": 40}},
    )
    assert together.status_code == 200
    assert together.json()["retention"] == {"trace_data_days": 40, "verdict_history_days": 40}
    raised = await app_client.patch(
        "/api/v1/settings",
        headers=admin_headers,
        json={"retention": {"trace_data_days": 50}},
    )
    assert raised.status_code == 422
    assert "trace_data_days (50)" in raised.json()["error"]["message"]


async def test_telemetry_default_from_env(
    settings: Settings, mem_stores: tuple[InMemoryEventStore, InMemoryMetaStore]
) -> None:
    app = create_app(settings.model_copy(update={"telemetry": 0}), *mem_stores)
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/api/v1/settings",
            headers={"Authorization": f"Bearer {settings.admin_token}"},
        )
    assert response.json()["telemetry"]["enabled"] is False
    assert response.json()["telemetry"]["disabled_by_environment"] is True
    assert "agents_demo" in response.json()["telemetry"]["payload_preview"]
    assert "agents_non_demo" in response.json()["telemetry"]["payload_preview"]
