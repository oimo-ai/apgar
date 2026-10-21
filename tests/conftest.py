from __future__ import annotations

import os
import secrets
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import httpx
import pytest
from httpx import ASGITransport

from apgar.api.app import create_app
from apgar.config import Settings
from apgar.security import SecretBox
from apgar.storage.clickhouse.client import create_client, ping
from apgar.storage.clickhouse.event_store import ClickHouseEventStore
from apgar.storage.clickhouse.meta_store import ClickHouseMetaStore
from apgar.storage.clickhouse.migrate import migrate
from apgar.storage.memory import InMemoryEventStore, InMemoryMetaStore


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    _ = config
    if os.environ.get("APGAR_RUN_SLOW") == "1":
        return
    skip_slow = pytest.mark.skip(reason="set APGAR_RUN_SLOW=1 to run slow tests")
    for item in items:
        if "slow" in item.keywords:
            item.add_marker(skip_slow)


@pytest.fixture
def settings() -> Settings:
    return Settings(
        secret_key="x" * 48,
        admin_token="admin-token-for-tests",
        clickhouse_url="http://localhost:18123",
        public_url="http://localhost:8080",
        # A .invalid host never resolves, so no test can reach the real telemetry project.
        telemetry_endpoint="https://telemetry.invalid/i/v0/e/",
    )


@pytest.fixture
def fixed_now() -> datetime:
    return datetime(2026, 10, 8, 9, 30, tzinfo=UTC)


@pytest.fixture
def mem_stores(settings: Settings) -> tuple[InMemoryEventStore, InMemoryMetaStore]:
    box = SecretBox(settings.secret_key, settings.secret_key_previous)
    return InMemoryEventStore(), InMemoryMetaStore(box)


@pytest.fixture
def admin_headers(settings: Settings) -> dict[str, str]:
    return {"Authorization": f"Bearer {settings.admin_token}"}


@pytest.fixture
async def app_client(
    settings: Settings,
    mem_stores: tuple[InMemoryEventStore, InMemoryMetaStore],
) -> AsyncIterator[httpx.AsyncClient]:
    event_store, meta_store = mem_stores
    app = create_app(settings, event_store, meta_store)
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.fixture
async def ch_database() -> AsyncIterator[
    tuple[Settings, ClickHouseEventStore, ClickHouseMetaStore]
]:
    url = os.environ.get("APGAR_TEST_CLICKHOUSE_URL", "http://localhost:18123")
    user = os.environ.get("APGAR_TEST_CLICKHOUSE_USER", "apgar")
    password = os.environ.get("APGAR_TEST_CLICKHOUSE_PASSWORD", "apgar_test")
    require = os.environ.get("APGAR_TEST_REQUIRE_CLICKHOUSE") == "1"
    admin_settings = Settings(
        secret_key="x" * 48,
        admin_token="admin-token-for-tests",
        clickhouse_url=url,
        clickhouse_user=user,
        clickhouse_password=password,
        clickhouse_database="default",
    )
    admin = None
    reachable = False
    try:
        admin = await create_client(admin_settings, database="default")
        reachable = await ping(admin)
    except Exception as exc:
        text = str(exc).lower()
        if not any(token in text for token in ("connect", "timed out", "timeout", "refused")):
            if admin is not None:
                await admin.close()
            raise
        reachable = False
    if not reachable:
        if admin is not None:
            await admin.close()
        if require:
            pytest.fail("ClickHouse is unreachable")
        pytest.skip("ClickHouse is unreachable")
    assert admin is not None
    database = "apgar_test_" + secrets.token_hex(4)
    db_client = None
    try:
        await admin.command(f"CREATE DATABASE {database}")
        test_settings = admin_settings.model_copy(update={"clickhouse_database": database})
        await migrate(test_settings)
        db_client = await create_client(test_settings)
        yield (
            test_settings,
            ClickHouseEventStore(db_client),
            ClickHouseMetaStore(
                db_client,
                SecretBox(test_settings.secret_key, test_settings.secret_key_previous),
            ),
        )
    finally:
        if db_client is not None:
            await db_client.close()
        await admin.command(f"DROP DATABASE IF EXISTS {database}")
        await admin.close()
