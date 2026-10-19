from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from apgar.config import Settings
from apgar.storage.clickhouse.client import create_client

MIGRATIONS_DIR = Path(__file__).parent / "migrations"
_MIGRATION_NAME = re.compile(r"^(\d{4})_([a-z0-9_]+)\.sql$")
_IDENTIFIER = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")
_STATEMENT_SPLIT = re.compile(r";[ \t]*\n")
_LOG = logging.getLogger("apgar.storage.clickhouse.migrate")

_SCHEMA_MIGRATIONS_DDL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
  version UInt32,
  name String,
  applied_at DateTime64(3, 'UTC') DEFAULT now64(3)
) ENGINE = MergeTree ORDER BY (version)
""".strip()


class MigrationError(Exception):
    pass


class SchemaVersionError(Exception):
    def __init__(self, found: int, expected: int) -> None:
        self.found = found
        self.expected = expected
        if found < expected:
            message = f"schema version {found} is behind expected {expected}; run apgar migrate"
        else:
            message = f"schema version {found} is newer than this image supports ({expected})"
        super().__init__(message)


def list_migrations(directory: Path | None = None) -> list[tuple[int, str, Path]]:
    root = MIGRATIONS_DIR if directory is None else directory
    found: list[tuple[int, str, Path]] = []
    if root.is_dir():
        for path in root.iterdir():
            match = _MIGRATION_NAME.match(path.name)
            if match is None:
                continue
            found.append((int(match.group(1)), match.group(2), path))
    found.sort(key=lambda item: (item[0], item[1]))
    versions = [version for version, _name, _path in found]
    if not found or versions != list(range(1, len(versions) + 1)):
        raise MigrationError("migration versions must be consecutive starting at 1")
    return found


def expected_schema_version() -> int:
    return list_migrations()[-1][0]


def _load_expected_schema_version() -> int:
    # A gap must not raise while the CLI module is imported, so `apgar migrate`
    # can print the message and exit 1 instead of dying in the import.
    try:
        return expected_schema_version()
    except MigrationError:
        return 0


EXPECTED_SCHEMA_VERSION = _load_expected_schema_version()


def split_statements(sql: str) -> list[str]:
    text = sql.replace("\r\n", "\n").replace("\r", "\n")
    statements: list[str] = []
    for chunk in _STATEMENT_SPLIT.split(text):
        if chunk.endswith(";"):
            chunk = chunk[:-1]
        kept = [
            line
            for line in chunk.splitlines()
            if line.strip() and not line.strip().startswith("--")
        ]
        if kept:
            statements.append("\n".join(kept).strip())
    return statements


def is_unknown_database(exc: BaseException) -> bool:
    text = str(exc).lower()
    if "unknown_database" in text or "code: 81" in text:
        return True
    return "database" in text and "exist" in text


async def ensure_database(settings: Settings) -> None:
    database = settings.clickhouse_database
    if _IDENTIFIER.match(database) is None:
        raise MigrationError(f"invalid database name: {database}")
    bare = settings.model_copy(update={"clickhouse_database": "default"})
    client = await create_client(bare, database="default")
    try:
        await client.command(f"CREATE DATABASE IF NOT EXISTS {database}")
    finally:
        await client.close()


async def current_version(client: Any) -> int:
    exists = await client.query("EXISTS TABLE schema_migrations")
    if not int(exists.result_rows[0][0]):
        return 0
    result = await client.query("SELECT max(version) FROM schema_migrations")
    value = result.result_rows[0][0]
    if value is None:
        return 0
    return int(value)


async def apply_sql(client: Any, sql: str) -> None:
    # Mutations (ALTER ... DELETE) run in the background unless waited for; a migration
    # is applied only once every row it removes is gone.
    for statement in split_statements(sql):
        await client.command(statement, settings={"mutations_sync": 2})


async def migrate(settings: Settings) -> int:
    migrations = list_migrations()
    await ensure_database(settings)
    client = await create_client(settings)
    applied = 0
    try:
        await client.command(_SCHEMA_MIGRATIONS_DDL)
        current = await current_version(client)
        for version, name, path in migrations:
            if version <= current:
                continue
            await apply_sql(client, path.read_text(encoding="utf-8"))
            await client.insert(
                "schema_migrations",
                [[version, name]],
                column_names=["version", "name"],
            )
            applied += 1
            _LOG.info("applied migration", extra={"version": version, "migration": name})
        version_now = await current_version(client)
    finally:
        await client.close()
    print(f"applied {applied} migrations", flush=True)
    return version_now


async def check_schema_version(client: Any) -> None:
    expected = expected_schema_version()
    try:
        found = await current_version(client)
    except Exception as exc:
        if is_unknown_database(exc):
            raise SchemaVersionError(0, expected) from exc
        raise
    if found != expected:
        raise SchemaVersionError(found, expected)
