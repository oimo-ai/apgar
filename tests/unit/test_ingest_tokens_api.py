from __future__ import annotations

import httpx

from apgar.domain.enums import OutputFormat
from tests.factories import make_agent
from tests.support import FIXTURE_NOW, MemStores


async def test_create_returns_plaintext_once(
    app_client: httpx.AsyncClient,
    admin_headers: dict[str, str],
    mem_stores: MemStores,
) -> None:
    response = await app_client.post(
        "/api/v1/ingest-tokens",
        headers=admin_headers,
        json={"name": "dev"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["token"].startswith("apg_ing_")
    assert body["token_prefix"] == body["token"][:12]
    assert "token_hash" not in body
    listed = await app_client.get("/api/v1/ingest-tokens", headers=admin_headers)
    assert listed.status_code == 200
    assert "token" not in listed.json()["items"][0]
    assert mem_stores


async def test_list_hides_hash(
    app_client: httpx.AsyncClient, admin_headers: dict[str, str]
) -> None:
    created = await app_client.post(
        "/api/v1/ingest-tokens",
        headers=admin_headers,
        json={"name": "dev", "auto_create_agents": False},
    )
    listed = await app_client.get("/api/v1/ingest-tokens", headers=admin_headers)
    item = listed.json()["items"][0]
    assert item["id"] == created.json()["id"]
    assert item["token_prefix"] == created.json()["token_prefix"]
    assert "token_hash" not in item
    assert item["auto_create_agents"] is False
    assert item["revoked_at"] is None


async def test_delete_revokes(app_client: httpx.AsyncClient, admin_headers: dict[str, str]) -> None:
    created = await app_client.post(
        "/api/v1/ingest-tokens",
        headers=admin_headers,
        json={"name": "dev"},
    )
    token_id = created.json()["id"]
    deleted = await app_client.delete(f"/api/v1/ingest-tokens/{token_id}", headers=admin_headers)
    assert deleted.status_code == 204
    listed = await app_client.get("/api/v1/ingest-tokens", headers=admin_headers)
    assert listed.json()["items"][0]["revoked_at"] is not None
    missing = await app_client.delete("/api/v1/ingest-tokens/missing", headers=admin_headers)
    assert missing.status_code == 404


async def test_scoped_token_requires_existing_agent(
    app_client: httpx.AsyncClient,
    admin_headers: dict[str, str],
    mem_stores: MemStores,
) -> None:
    missing = await app_client.post(
        "/api/v1/ingest-tokens",
        headers=admin_headers,
        json={"name": "scoped", "agent": "billing-copilot"},
    )
    assert missing.status_code == 404
    _event, meta = mem_stores
    await meta.upsert_agent(make_agent(FIXTURE_NOW, output_format=OutputFormat.text))
    created = await app_client.post(
        "/api/v1/ingest-tokens",
        headers=admin_headers,
        json={"name": "scoped", "agent": "billing-copilot"},
    )
    assert created.status_code == 201
    assert created.json()["agent"] == "billing-copilot"


async def test_requires_admin(app_client: httpx.AsyncClient) -> None:
    response = await app_client.get("/api/v1/ingest-tokens")
    assert response.status_code == 401
    denied = await app_client.post(
        "/api/v1/ingest-tokens",
        headers={"authorization": "Bearer wrong-token-value"},
        json={"name": "dev"},
    )
    assert denied.status_code == 401


async def test_list_paginates(app_client: httpx.AsyncClient, admin_headers: dict[str, str]) -> None:
    for name in ("a", "b", "c"):
        created = await app_client.post(
            "/api/v1/ingest-tokens",
            headers=admin_headers,
            json={"name": name},
        )
        assert created.status_code == 201
    listed = await app_client.get(
        "/api/v1/ingest-tokens",
        headers=admin_headers,
        params={"limit": 1, "offset": 1},
    )
    body = listed.json()
    assert listed.status_code == 200
    assert body["total"] == 3
    assert len(body["items"]) == 1
    rejected = await app_client.get(
        "/api/v1/ingest-tokens",
        headers=admin_headers,
        params={"limit": 501},
    )
    assert rejected.status_code == 422
