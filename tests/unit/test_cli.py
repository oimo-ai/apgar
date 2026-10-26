from __future__ import annotations

from click.testing import CliRunner

from apgar.cli import main


def test_cli_lists_commands() -> None:
    result = CliRunner().invoke(main, ["--help"])
    assert result.exit_code == 0
    for name in ("migrate", "wait-for-schema", "api", "worker"):
        assert name in result.output


def test_migrate_and_wait_take_a_timeout() -> None:
    for command, default in (("migrate", "0"), ("wait-for-schema", "300")):
        result = CliRunner().invoke(main, [command, "--help"])
        assert result.exit_code == 0
        assert "--timeout" in result.output
        assert f"[default: {default}" in result.output
    rejected = CliRunner().invoke(main, ["migrate", "--timeout", "-1"])
    assert rejected.exit_code == 2
