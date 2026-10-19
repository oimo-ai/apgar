from __future__ import annotations

import pytest

from apgar.config import Settings
from apgar.storage.clickhouse.event_store import ClickHouseEventStore
from apgar.storage.clickhouse.meta_store import ClickHouseMetaStore
from apgar.storage.clickhouse.migrate import (
    SchemaVersionError,
    check_schema_version,
    current_version,
    migrate,
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
