from __future__ import annotations

from typing import Any

import clickhouse_connect
import pytest

from apgar.config import Settings
from apgar.storage.clickhouse.client import create_client


async def _connect_kwargs(monkeypatch: pytest.MonkeyPatch, settings: Settings) -> dict[str, Any]:
    captured: dict[str, Any] = {}

    async def fake_get_async_client(**kwargs: Any) -> object:
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(clickhouse_connect, "get_async_client", fake_get_async_client)
    await create_client(settings)
    return captured


async def test_https_verifies_with_the_system_store_by_default(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    secure = settings.model_copy(update={"clickhouse_url": "https://ch.example.com"})
    kwargs = await _connect_kwargs(monkeypatch, secure)
    assert kwargs["host"] == "ch.example.com"
    assert kwargs["port"] == 8443
    assert kwargs["secure"] is True
    assert kwargs["verify"] is True
    assert "ca_cert" not in kwargs


async def test_custom_ca_and_verify_reach_the_driver(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    custom = settings.model_copy(
        update={
            "clickhouse_url": "https://clickhouse.apgar.svc:8443",
            "clickhouse_ca_cert": "/etc/apgar/clickhouse-ca/ca.crt",
            "clickhouse_verify": False,
        }
    )
    kwargs = await _connect_kwargs(monkeypatch, custom)
    assert kwargs["ca_cert"] == "/etc/apgar/clickhouse-ca/ca.crt"
    assert kwargs["verify"] is False
