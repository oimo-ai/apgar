from __future__ import annotations

import json

import httpx
import respx

from apgar.actions.messages import webhook_payload
from apgar.actions.webhook import sign
from apgar.domain.time import from_iso
from tests.factories import make_agent, make_release
from tests.support import MemStores


async def test_create_redaction_and_patch(
    app_client: httpx.AsyncClient, admin_headers: dict[str, str], mem_stores: MemStores
) -> None:
    langfuse = await app_client.post(
        "/api/v1/connections",
        headers=admin_headers,
        json={
            "name": "lf",
            "type": "langfuse",
            "config": {
                "host": "https://cloud.langfuse.com/",
                "public_key": "pk",
                "secret_key": "sk-test-value",
            },
        },
    )
    assert langfuse.status_code == 201
    masked = langfuse.json()["config"]
    assert masked["host"] == "https://cloud.langfuse.com"
    assert masked["secret_key"].endswith("alue")
    assert masked["secret_key"].startswith("••••")
    prefixed = await app_client.post(
        "/api/v1/connections",
        headers=admin_headers,
        json={
            "name": "lf2",
            "type": "langfuse",
            "config": {
                "host": "https://cloud.langfuse.com",
                "public_key": "pk",
                "secret_key": "sk-lf-0123-abcd",
            },
        },
    )
    assert prefixed.json()["config"]["secret_key"] == "sk-lf-••••abcd"
    slack = await app_client.post(
        "/api/v1/connections",
        headers=admin_headers,
        json={
            "name": "sl",
            "type": "slack",
            "config": {"webhook_url": "https://hooks.slack.com/services/T/B/x"},
        },
    )
    assert slack.json()["config"]["webhook_url"] == "https://hooks.slack.com/services/T/B/x"
    hook = await app_client.post(
        "/api/v1/connections",
        headers=admin_headers,
        json={
            "name": "wh",
            "type": "webhook",
            "config": {"url": "https://example.test/hook", "secret": "s" * 16},
        },
    )
    assert hook.json()["config"]["secret"] == "••••"
    patched = await app_client.patch(
        f"/api/v1/connections/{langfuse.json()['id']}",
        headers=admin_headers,
        json={"name": "lf-renamed", "config": {"secret_key": masked["secret_key"]}},
    )
    assert patched.status_code == 200
    _event, meta = mem_stores
    stored = await meta.get_connection(langfuse.json()["id"])
    assert stored is not None
    assert stored.config["secret_key"] == "sk-test-value"
    assert stored.name == "lf-renamed"


async def test_delete_conflict_when_referenced(
    app_client: httpx.AsyncClient, admin_headers: dict[str, str]
) -> None:
    created = await app_client.post(
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
    connection_id = created.json()["id"]
    await app_client.post(
        "/api/v1/agents",
        headers=admin_headers,
        json={
            "name": "lf-billing",
            "source": "langfuse",
            "langfuse_connection": connection_id,
            "filter": {"trace_name": "billing-copilot"},
        },
    )
    conflict = await app_client.delete(
        f"/api/v1/connections/{connection_id}", headers=admin_headers
    )
    assert conflict.status_code == 409


async def test_connection_probes(
    app_client: httpx.AsyncClient, admin_headers: dict[str, str]
) -> None:
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
    connection_id = langfuse.json()["id"]
    with respx.mock:
        respx.get("https://cloud.langfuse.com/api/public/projects").mock(
            return_value=httpx.Response(200, json={"data": [{"id": "proj-123"}]})
        )
        ok = await app_client.post(
            f"/api/v1/connections/{connection_id}/test", headers=admin_headers
        )
    assert ok.json()["status"] == "ok"
    listed = await app_client.get("/api/v1/connections", headers=admin_headers)
    item = next(row for row in listed.json()["items"] if row["id"] == connection_id)
    assert item["config"]["project_id"] == "proj-123"
    with respx.mock:
        respx.get("https://cloud.langfuse.com/api/public/projects").mock(
            return_value=httpx.Response(500, text="down")
        )
        failed = await app_client.post(
            f"/api/v1/connections/{connection_id}/test", headers=admin_headers
        )
    assert failed.status_code == 200
    assert failed.json()["status"] == "error"
    slack = await app_client.post(
        "/api/v1/connections",
        headers=admin_headers,
        json={
            "name": "sl",
            "type": "slack",
            "config": {"webhook_url": "https://hooks.slack.com/services/T/B/x"},
        },
    )
    hook = await app_client.post(
        "/api/v1/connections",
        headers=admin_headers,
        json={
            "name": "wh",
            "type": "webhook",
            "config": {"url": "https://example.test/hook", "secret": "s" * 16},
        },
    )
    seen: dict[str, str] = {}

    def _capture(request: httpx.Request) -> httpx.Response:
        seen["signature"] = request.headers["X-Apgar-Signature"]
        seen["timestamp"] = request.headers["X-Apgar-Timestamp"]
        seen["event"] = request.headers["X-Apgar-Event"]
        seen["body"] = request.content.decode()
        return httpx.Response(204)

    with respx.mock:
        respx.post("https://hooks.slack.com/services/T/B/x").mock(
            return_value=httpx.Response(200, text="ok")
        )
        respx.post("https://example.test/hook").mock(side_effect=_capture)
        assert (
            await app_client.post(
                f"/api/v1/connections/{slack.json()['id']}/test", headers=admin_headers
            )
        ).json()["status"] == "ok"
        hook_result = await app_client.post(
            f"/api/v1/connections/{hook.json()['id']}/test", headers=admin_headers
        )
    assert hook_result.json()["status"] == "ok"
    payload = json.loads(seen["body"])
    stamp = int(from_iso(payload["sent_at"]).timestamp())
    assert seen["timestamp"] == str(stamp)
    assert seen["signature"] == sign("s" * 16, stamp, seen["body"].encode())
    assert seen["event"] == "test"
    sent_at = from_iso(payload["sent_at"])
    live = webhook_payload(
        "regression",
        make_agent(sent_at),
        make_release(sent_at),
        {},
        "",
        sent_at,
        False,
        idempotency_key="k",
        previous_verdict=None,
    )
    assert set(payload) == set(live)
    assert payload["event"] == "test"
    assert payload["text"] == "Apgar connection test"
    for status in (400, 503):
        with respx.mock:
            respx.post("https://example.test/hook").mock(return_value=httpx.Response(status))
            failed_hook = await app_client.post(
                f"/api/v1/connections/{hook.json()['id']}/test", headers=admin_headers
            )
        assert failed_hook.json()["status"] == "error"
        assert failed_hook.json()["detail"].startswith(f"HTTP {status}")
