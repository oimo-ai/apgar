from __future__ import annotations

from pathlib import Path

import pytest

from apgar.storage.clickhouse.migrate import (
    EXPECTED_SCHEMA_VERSION,
    MigrationError,
    list_migrations,
    split_statements,
)


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
