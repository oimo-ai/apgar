from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace

import httpx
import pytest
from httpx import ASGITransport
from starlette.requests import Request

from apgar.api.app import create_app
from apgar.api.deps import _client_ip
from apgar.api.session import issue_session, verify_session_cookie
from apgar.config import Settings
from apgar.storage.memory import InMemoryEventStore, InMemoryMetaStore
from tests.support import Clock


def _cookie(response: httpx.Response) -> str:
    header = response.headers.get("set-cookie")
    assert isinstance(header, str)
    return header


async def test_admin_bearer_ok(
    app_client: httpx.AsyncClient, admin_headers: dict[str, str]
) -> None:
    response = await app_client.get("/api/v1/agents", headers=admin_headers)
    assert response.status_code == 200
    assert response.json()["total"] == 0


async def test_only_the_admin_token_is_accepted_as_bearer(app_client: httpx.AsyncClient) -> None:
    response = await app_client.get(
        "/api/v1/agents", headers={"Authorization": "Bearer apg_api_0123456789abcdef"}
    )
    assert response.status_code == 401


async def test_ingest_token_rejected_on_api(
    app_client: httpx.AsyncClient, admin_headers: dict[str, str]
) -> None:
    created = await app_client.post(
        "/api/v1/ingest-tokens",
        headers=admin_headers,
        json={"name": "edge"},
    )
    token = created.json()["token"]
    response = await app_client.get("/api/v1/agents", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401


async def test_login_sets_cookie_attributes(
    app_client: httpx.AsyncClient, settings: Settings
) -> None:
    response = await app_client.post("/api/v1/auth/login", json={"token": settings.admin_token})
    assert response.status_code == 204
    cookie = _cookie(response).lower()
    assert "httponly" in cookie
    assert "samesite=strict" in cookie
    assert "path=/" in cookie
    assert "max-age=86400" in cookie
    assert "secure" not in cookie


async def test_login_secure_with_forwarded_proto(
    app_client: httpx.AsyncClient, settings: Settings
) -> None:
    response = await app_client.post(
        "/api/v1/auth/login",
        json={"token": settings.admin_token},
        headers={"X-Forwarded-Proto": "https"},
    )
    assert "secure" in _cookie(response).lower()


async def test_login_secure_with_setting(
    settings: Settings, mem_stores: tuple[InMemoryEventStore, InMemoryMetaStore]
) -> None:
    app = create_app(settings.model_copy(update={"cookie_secure": True}), *mem_stores)
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/v1/auth/login", json={"token": settings.admin_token})
    assert "secure" in _cookie(response).lower()


async def test_cookie_without_csrf_header_403_on_post(
    app_client: httpx.AsyncClient, settings: Settings
) -> None:
    await app_client.post("/api/v1/auth/login", json={"token": settings.admin_token})
    response = await app_client.post("/api/v1/ingest-tokens", json={"name": "ci"})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"


async def test_cookie_get_without_header_ok(
    app_client: httpx.AsyncClient, settings: Settings
) -> None:
    await app_client.post("/api/v1/auth/login", json={"token": settings.admin_token})
    response = await app_client.get("/api/v1/agents")
    assert response.status_code == 200


async def test_expired_cookie_401(
    settings: Settings,
    mem_stores: tuple[InMemoryEventStore, InMemoryMetaStore],
    fixed_now: object,
) -> None:
    from datetime import datetime

    assert isinstance(fixed_now, datetime)
    clock = Clock(fixed_now)
    app = create_app(settings, *mem_stores, clock)
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await client.post("/api/v1/auth/login", json={"token": settings.admin_token})
        clock.now = fixed_now + timedelta(seconds=86401)
        response = await client.get("/api/v1/auth/session")
    assert response.status_code == 401


def test_cookie_rejects_noncanonical_signature(settings: Settings, fixed_now: object) -> None:
    from datetime import datetime

    assert isinstance(fixed_now, datetime)
    issued = issue_session(settings.secret_key, fixed_now)
    payload, signature = issued.split(".", 1)
    padding_bit = signature[:-1] + ("A" if signature[-1] != "A" else "B")
    rejected = verify_session_cookie(f"{payload}.{padding_bit}", settings.secret_key, fixed_now)
    assert rejected is False
    noisy = signature[:4] + "!" + signature[4:]
    noisy_rejected = verify_session_cookie(f"{payload}.{noisy}", settings.secret_key, fixed_now)
    assert noisy_rejected is False
    assert verify_session_cookie(issued, settings.secret_key, fixed_now) is True


async def test_tampered_cookie_401(app_client: httpx.AsyncClient, settings: Settings) -> None:
    await app_client.post("/api/v1/auth/login", json={"token": settings.admin_token})
    raw = app_client.cookies.get("apgar_session")
    assert raw is not None
    flipped = raw[:-1] + ("A" if raw[-1] != "A" else "B")
    app_client.cookies.clear()
    app_client.cookies.set("apgar_session", flipped, domain="test.local", path="/")
    response = await app_client.get("/api/v1/auth/session")
    assert response.status_code == 401


async def test_login_rate_limit_429(
    app_client: httpx.AsyncClient,
) -> None:
    headers = {"X-Forwarded-For": "203.0.113.9"}
    for _ in range(10):
        response = await app_client.post(
            "/api/v1/auth/login", json={"token": "not-the-admin-token"}, headers=headers
        )
        assert response.status_code == 401
    blocked = await app_client.post(
        "/api/v1/auth/login", json={"token": "not-the-admin-token"}, headers=headers
    )
    assert blocked.status_code == 429
    assert blocked.json()["error"]["code"] == "rate_limited"


async def test_login_rate_limit_ignores_a_spoofed_forwarded_for(
    app_client: httpx.AsyncClient,
) -> None:
    for attempt in range(10):
        headers = {"X-Forwarded-For": f"198.51.100.{attempt}, 203.0.113.9"}
        response = await app_client.post(
            "/api/v1/auth/login", json={"token": "not-the-admin-token"}, headers=headers
        )
        assert response.status_code == 401
    blocked = await app_client.post(
        "/api/v1/auth/login",
        json={"token": "not-the-admin-token"},
        headers={"X-Forwarded-For": "198.51.100.99, 203.0.113.9"},
    )
    assert blocked.status_code == 429


def _request(hops: int, forwarded: str | None) -> Request:
    settings = SimpleNamespace(trusted_proxy_hops=hops)
    headers = [] if forwarded is None else [(b"x-forwarded-for", forwarded.encode())]
    scope = {
        "type": "http",
        "headers": headers,
        "client": ("10.0.0.5", 41000),
        "app": SimpleNamespace(state=SimpleNamespace(settings=settings)),
    }
    return Request(scope)


@pytest.mark.parametrize(
    ("hops", "forwarded", "expected"),
    [
        (1, "203.0.113.9", "203.0.113.9"),
        (1, "spoofed, 203.0.113.9", "203.0.113.9"),
        (2, "spoofed, 203.0.113.9, 10.0.0.2", "203.0.113.9"),
        (3, "203.0.113.9, 10.0.0.2", "203.0.113.9"),
        (0, "203.0.113.9", "10.0.0.5"),
        (1, None, "10.0.0.5"),
        (1, " , ", "10.0.0.5"),
    ],
)
def test_client_ip_trusts_only_the_configured_proxies(
    hops: int, forwarded: str | None, expected: str
) -> None:
    assert _client_ip(_request(hops, forwarded)) == expected


async def test_logout_clears_cookie(app_client: httpx.AsyncClient, settings: Settings) -> None:
    await app_client.post("/api/v1/auth/login", json={"token": settings.admin_token})
    response = await app_client.post("/api/v1/auth/logout")
    assert response.status_code == 204
    assert "max-age=0" in _cookie(response).lower()


async def test_session_endpoint(
    app_client: httpx.AsyncClient, settings: Settings, admin_headers: dict[str, str]
) -> None:
    missing = await app_client.get("/api/v1/auth/session")
    assert missing.status_code == 401
    await app_client.post("/api/v1/auth/login", json={"token": settings.admin_token})
    response = await app_client.get("/api/v1/auth/session")
    body = response.json()
    assert body == {"authenticated": True, "kind": "session"}
    bearer = await app_client.get("/api/v1/auth/session", headers=admin_headers)
    assert bearer.json()["kind"] == "admin"
