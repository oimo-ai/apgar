from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
import respx

from apgar.connectors.langfuse.client import (
    LangfuseClient,
    LangfuseClientError,
    LangfuseRateLimited,
)

_URL = "http://langfuse.test/api/public/v2/observations"
_NOW = datetime(2026, 10, 8, 9, 30, tzinfo=UTC)


def _client(http: httpx.AsyncClient) -> LangfuseClient:
    return LangfuseClient("http://langfuse.test", "pk-test", "sk-test", http, lambda: _NOW, "lf")


async def test_basic_auth_and_pagination() -> None:
    page = json.loads(Path("tests/fixtures/langfuse/roots_page1.json").read_text())
    with respx.mock:
        route = respx.get(_URL).mock(return_value=httpx.Response(200, json=page))
        async with httpx.AsyncClient() as http:
            result = await _client(http).list_observations([("limit", "1000")])
    assert result.cursor == "c1"
    assert len(result.data) == 3
    header = route.calls[0].request.headers["authorization"]
    assert header.startswith("Basic ")
    assert route.calls[0].request.headers["user-agent"].startswith("apgar/")


async def test_retry_after_and_server_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    slept: list[float] = []

    async def _sleep(delay: float) -> None:
        slept.append(delay)

    monkeypatch.setattr(asyncio, "sleep", _sleep)
    with respx.mock:
        respx.get(_URL).mock(
            side_effect=[
                httpx.Response(429, headers={"Retry-After": "1"}, json={"error": "rate"}),
                httpx.Response(200, json={"data": [], "meta": {}}),
            ]
        )
        async with httpx.AsyncClient() as http:
            page = await _client(http).list_observations([])
    assert page.data == []
    assert slept == [1.0]
    slept.clear()
    with respx.mock:
        respx.get(_URL).mock(
            side_effect=[
                httpx.Response(503, text="down"),
                httpx.Response(200, json={"data": [{"id": "1"}], "meta": {}}),
            ]
        )
        async with httpx.AsyncClient() as http:
            page = await _client(http).list_observations([])
    assert page.data == [{"id": "1"}]
    assert len(slept) == 1


async def test_client_error_does_not_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    slept: list[float] = []

    async def _sleep(delay: float) -> None:
        slept.append(delay)

    monkeypatch.setattr(asyncio, "sleep", _sleep)
    with respx.mock:
        respx.get(_URL).mock(return_value=httpx.Response(400, text="bad filter"))
        async with httpx.AsyncClient() as http:
            with pytest.raises(LangfuseClientError) as exc:
                await _client(http).list_observations([])
    assert exc.value.status_code == 400
    assert slept == []


async def test_eight_attempts_then_rate_limited(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _sleep(_delay: float) -> None:
        return None

    monkeypatch.setattr(asyncio, "sleep", _sleep)
    with respx.mock:
        route = respx.get(_URL).mock(return_value=httpx.Response(429, text="slow"))
        async with httpx.AsyncClient() as http:
            with pytest.raises(LangfuseRateLimited):
                await _client(http).list_observations([])
    assert route.call_count == 8
