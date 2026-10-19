from __future__ import annotations

from click.testing import CliRunner

from apgar.cli import main


def test_cli_lists_commands() -> None:
    result = CliRunner().invoke(main, ["--help"])
    assert result.exit_code == 0
    for name in ("migrate", "api", "worker"):
        assert name in result.output
