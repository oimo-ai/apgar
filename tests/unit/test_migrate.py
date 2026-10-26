from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path

import pytest
from clickhouse_connect.driver.exceptions import DatabaseError, OperationalError

from apgar.config import Settings
from apgar.storage.clickhouse import migrate as migrate_module
from apgar.storage.clickhouse.migrate import (
    EXPECTED_SCHEMA_VERSION,
    MigrationError,
    SchemaVersionError,
    list_migrations,
    retry_while_unreachable,
    split_statements,
    wait_for_schema,
)


class FakeTime:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def _failing_then(results: list[BaseException | int]) -> Callable[[], Awaitable[int]]:
    async def action() -> int:
        result = results.pop(0)
        if isinstance(result, BaseException):
            raise result
        return result

    return action


def test_list_migrations_sorted() -> None:
    found = list_migrations()
    versions = [version for version, _name, _path in found]
    assert versions == sorted(versions)
    assert versions[0] == 1


def test_gap_in_versions_rejected(tmp_path: Path) -> None:
    (tmp_path / "0001_initial.sql").write_text("SELECT 1\n;\n", encoding="utf-8")
    (tmp_path / "0003_later.sql").write_text("SELECT 1\n;\n", encoding="utf-8")
    with pytest.raises(MigrationError, match="consecutive"):
        list_migrations(tmp_path)


def test_split_statements_ignores_comments_and_blank() -> None:
    sql = "\n".join(
        [
            "-- header",
            "SELECT 1",
            ";",
            "",
            "-- only a comment",
            ";",
            "SELECT 2",
            ";",
        ]
    )
    assert split_statements(sql) == ["SELECT 1", "SELECT 2"]
    inline = "CREATE TABLE a (id UInt8);\nCREATE TABLE b (id UInt8);\n"
    assert split_statements(inline) == [
        "CREATE TABLE a (id UInt8)",
        "CREATE TABLE b (id UInt8)",
    ]
    crlf = "SELECT 1\r\n;\r\nSELECT 2\r\n;\r\n"
    assert split_statements(crlf) == ["SELECT 1", "SELECT 2"]


def test_expected_schema_version_equals_file_count() -> None:
    assert len(list_migrations()) == EXPECTED_SCHEMA_VERSION


async def test_retry_waits_while_clickhouse_is_unreachable() -> None:
    clock = FakeTime()
    unreachable = OperationalError("Network Error: connect call failed")
    action = _failing_then([unreachable, unreachable, 7])
    assert await retry_while_unreachable(action, 10, clock.sleep, clock.monotonic) == 7
    assert clock.sleeps == [2.0, 2.0]


async def test_retry_gives_up_at_the_timeout() -> None:
    clock = FakeTime()
    action = _failing_then([OperationalError("Network Error")] * 10)
    with pytest.raises(OperationalError):
        await retry_while_unreachable(action, 3, clock.sleep, clock.monotonic)
    assert clock.sleeps == [2.0, 2.0]


async def test_retry_does_not_retry_other_errors() -> None:
    clock = FakeTime()
    action = _failing_then([DatabaseError("Code: 516. Authentication failed"), 1])
    with pytest.raises(DatabaseError):
        await retry_while_unreachable(action, 60, clock.sleep, clock.monotonic)
    assert clock.sleeps == []


async def test_zero_timeout_tries_once() -> None:
    clock = FakeTime()
    action = _failing_then([OperationalError("Network Error"), 1])
    with pytest.raises(OperationalError):
        await retry_while_unreachable(action, 0, clock.sleep, clock.monotonic)


def _stored_versions(monkeypatch: pytest.MonkeyPatch, results: list[BaseException | int]) -> None:
    action = _failing_then(results)

    async def stored(_settings: Settings) -> int:
        return await action()

    monkeypatch.setattr(migrate_module, "stored_schema_version", stored)


async def test_wait_for_schema_returns_once_migrated(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    clock = FakeTime()
    unreachable = OperationalError("Network Error")
    _stored_versions(monkeypatch, [unreachable, 0, 0, EXPECTED_SCHEMA_VERSION])
    found = await wait_for_schema(settings, 60, clock.sleep, clock.monotonic)
    assert found == EXPECTED_SCHEMA_VERSION
    assert clock.sleeps == [2.0, 2.0, 2.0]


async def test_wait_for_schema_fails_fast_on_a_newer_schema(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    clock = FakeTime()
    _stored_versions(monkeypatch, [EXPECTED_SCHEMA_VERSION + 1])
    with pytest.raises(SchemaVersionError, match="newer than this image supports"):
        await wait_for_schema(settings, 60, clock.sleep, clock.monotonic)
    assert clock.sleeps == []


async def test_wait_for_schema_times_out_behind(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    clock = FakeTime()
    _stored_versions(monkeypatch, [0] * 10)
    with pytest.raises(SchemaVersionError, match="behind expected"):
        await wait_for_schema(settings, 5, clock.sleep, clock.monotonic)
    assert clock.now >= 5
