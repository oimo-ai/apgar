from __future__ import annotations

import secrets

import pytest

from apgar.config import Settings
from apgar.storage.clickhouse.event_store import ClickHouseEventStore
from apgar.storage.clickhouse.meta_store import ClickHouseMetaStore
from apgar.storage.clickhouse.migrate import (
    EXPECTED_SCHEMA_VERSION,
    SchemaVersionError,
    check_schema_version,
    current_version,
    migrate,
    stored_schema_version,
    wait_for_schema,
)

pytestmark = pytest.mark.integration

_TABLES = {
    "schema_migrations",
    "spans",
    "trace_state",
    "turns",
    "tool_calls",
    "agents",
    "connections",
    "ingest_tokens",
    "settings",
    "sync_state",
    "releases",
    "release_events",
    "verdict_evaluations",
    "notifications",
    "job_requests",
}


async def test_migrate_creates_all_tables(
    ch_database: tuple[Settings, ClickHouseEventStore, ClickHouseMetaStore],
) -> None:
    _settings, _event_store, meta = ch_database
    result = await meta.client.query(
        "SELECT name FROM system.tables WHERE database = currentDatabase() AND name NOT LIKE '.%'"
    )
    names = {str(row[0]) for row in result.result_rows}
    assert names == _TABLES


async def test_migrate_is_idempotent(
    ch_database: tuple[Settings, ClickHouseEventStore, ClickHouseMetaStore],
    capsys: pytest.CaptureFixture[str],
) -> None:
    settings, _event_store, meta = ch_database
    before = await current_version(meta.client)
    capsys.readouterr()
    again = await migrate(settings)
    assert again == before
    assert "applied 0 migrations" in capsys.readouterr().out


async def test_schema_version_gate_behind(
    ch_database: tuple[Settings, ClickHouseEventStore, ClickHouseMetaStore],
) -> None:
    _settings, _event_store, meta = ch_database
    await meta.client.command("TRUNCATE TABLE schema_migrations")
    with pytest.raises(SchemaVersionError, match="behind expected"):
        await check_schema_version(meta.client)


async def test_schema_version_gate_ahead(
    ch_database: tuple[Settings, ClickHouseEventStore, ClickHouseMetaStore],
) -> None:
    _settings, _event_store, meta = ch_database
    await meta.client.insert(
        "schema_migrations",
        [[999, "future"]],
        column_names=["version", "name"],
    )
    with pytest.raises(SchemaVersionError, match="newer than this image supports"):
        await check_schema_version(meta.client)


async def test_migrate_creates_a_missing_database(
    ch_database: tuple[Settings, ClickHouseEventStore, ClickHouseMetaStore],
) -> None:
    settings, _event_store, meta = ch_database
    database = settings.clickhouse_database + "_new"
    fresh = settings.model_copy(update={"clickhouse_database": database})
    try:
        assert await stored_schema_version(fresh) == 0
        assert await migrate(fresh, timeout_seconds=5) == EXPECTED_SCHEMA_VERSION
        assert await wait_for_schema(fresh, 0) == EXPECTED_SCHEMA_VERSION
    finally:
        await meta.client.command(f"DROP DATABASE IF EXISTS {database}")


async def test_migrate_with_a_user_limited_to_its_database(
    ch_database: tuple[Settings, ClickHouseEventStore, ClickHouseMetaStore],
) -> None:
    settings, _event_store, meta = ch_database
    database = settings.clickhouse_database + "_scoped"
    user = "apgar_scoped_" + secrets.token_hex(4)
    password = secrets.token_hex(16)
    await meta.client.command(f"CREATE DATABASE {database}")
    await meta.client.command(f"CREATE USER {user} IDENTIFIED BY '{password}'")
    try:
        await meta.client.command(f"GRANT ALL ON {database}.* TO {user}")
        scoped = settings.model_copy(
            update={
                "clickhouse_database": database,
                "clickhouse_user": user,
                "clickhouse_password": password,
            }
        )
        assert await migrate(scoped) == EXPECTED_SCHEMA_VERSION
        assert await wait_for_schema(scoped, 0) == EXPECTED_SCHEMA_VERSION
    finally:
        await meta.client.command(f"DROP USER IF EXISTS {user}")
        await meta.client.command(f"DROP DATABASE IF EXISTS {database}")
