from __future__ import annotations

import httpx
import pytest

CASES = [
    ("GET", "/healthz", None, "public"),
    ("GET", "/readyz", None, "public"),
    ("GET", "/metrics", None, "public"),
    ("POST", "/v1/traces", b"", "ingest"),
    ("GET", "/api/v1/agents", None, "admin"),
    ("POST", "/api/v1/agents", {"name": "scope-agent", "source": "otlp"}, "admin"),
    ("GET", "/api/v1/agents/missing", None, "admin"),
    ("PATCH", "/api/v1/agents/missing", {}, "admin"),
    ("DELETE", "/api/v1/agents/missing", None, "admin"),
    ("GET", "/api/v1/agents/missing/releases", None, "admin"),
    ("GET", "/api/v1/agents/missing/releases/rel", None, "admin"),
    ("POST", "/api/v1/agents/missing/releases/rel/baseline", None, "admin"),
    ("POST", "/api/v1/agents/missing/releases/rel/expected-changes", None, "admin"),
    ("POST", "/api/v1/agents/missing/releases/rel/stop", None, "admin"),
    ("GET", "/api/v1/agents/missing/releases/rel/events", None, "admin"),
    ("GET", "/api/v1/agents/missing/releases/rel/evaluations", None, "admin"),
    ("GET", "/api/v1/connections", None, "admin"),
    (
        "POST",
        "/api/v1/connections",
        {
            "name": "slack-scope",
            "type": "slack",
            "config": {"webhook_url": "https://hooks.slack.com/services/abc"},
        },
        "admin",
    ),
    ("PATCH", "/api/v1/connections/missing", {"name": "renamed"}, "admin"),
    ("DELETE", "/api/v1/connections/missing", None, "admin"),
    ("POST", "/api/v1/connections/missing/test", None, "admin"),
    ("GET", "/api/v1/ingest-tokens", None, "admin"),
    ("POST", "/api/v1/ingest-tokens", {"name": "scope"}, "admin"),
    ("DELETE", "/api/v1/ingest-tokens/missing", None, "admin"),
    ("GET", "/api/v1/settings", None, "admin"),
    ("PATCH", "/api/v1/settings", {}, "admin"),
    ("GET", "/api/v1/notifications", None, "admin"),
]
PRINCIPALS = ["admin", "none"]


def _allowed(principal: str, required: str) -> bool:
    if required == "public":
        return True
    if required == "ingest":
        return False
    return principal == "admin"


@pytest.mark.parametrize("method,path,body,required", CASES)
@pytest.mark.parametrize("principal", PRINCIPALS)
async def test_access_matrix(
    app_client: httpx.AsyncClient,
    admin_headers: dict[str, str],
    method: str,
    path: str,
    body: object,
    required: str,
    principal: str,
) -> None:
    headers = dict(admin_headers) if principal == "admin" else {}
    kwargs: dict[str, object] = {"headers": headers}
    if isinstance(body, bytes):
        kwargs["content"] = body
    elif body is not None:
        kwargs["json"] = body
    response = await app_client.request(method, path, **kwargs)  # type: ignore[arg-type]
    if required == "public":
        assert response.status_code == 200
        return
    if _allowed(principal, required):
        assert response.status_code not in {401, 403}
    else:
        assert response.status_code == 401
