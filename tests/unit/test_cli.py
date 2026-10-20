from __future__ import annotations

from pathlib import Path

import pytest
import uvicorn
from click.testing import CliRunner

from apgar import cli
from apgar.cli import main
from apgar.config import Settings
from apgar.security import SecretBox
from apgar.storage.memory import InMemoryEventStore, InMemoryMetaStore
from apgar.worker import main as worker_main


class _Client:
    async def close(self) -> None:
        return None


@pytest.fixture
def invalid_config_file(
    settings: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "apgar.yaml"
    path.write_text("version: 2\n", encoding="utf-8")
    configured = settings.model_copy(update={"config_file": str(path)})
    meta = InMemoryMetaStore(SecretBox(settings.secret_key, None))

    async def create_client(_settings: Settings) -> _Client:
        return _Client()

    async def check_schema_version(_client: object) -> None:
        return None

    async def serve(_server: uvicorn.Server, sockets: object = None) -> None:
        return None

    monkeypatch.setattr(cli, "load_settings", lambda: configured)
    monkeypatch.setattr(cli, "setup_logging", lambda level: None)
    monkeypatch.setattr(cli, "create_client", create_client)
    monkeypatch.setattr(cli, "check_schema_version", check_schema_version)
    monkeypatch.setattr(cli, "_meta", lambda client, value: meta)
    monkeypatch.setattr(cli, "ClickHouseEventStore", lambda client: InMemoryEventStore())
    monkeypatch.setattr(uvicorn.Server, "serve", serve)
    monkeypatch.setattr(worker_main, "start_http_server", lambda port: None)
    monkeypatch.setattr(worker_main, "register_jobs", lambda *args: [])


def test_cli_lists_commands() -> None:
    result = CliRunner().invoke(main, ["--help"])
    assert result.exit_code == 0
    for name in ("migrate", "api", "worker"):
        assert name in result.output


@pytest.mark.usefixtures("invalid_config_file")
def test_api_does_not_read_config_file() -> None:
    result = CliRunner().invoke(main, ["api"])
    assert result.exit_code == 0, result.output


@pytest.mark.usefixtures("invalid_config_file")
def test_worker_rejects_invalid_config_file() -> None:
    result = CliRunner().invoke(main, ["worker"])
    assert result.exit_code == 2
    assert "version: must be 1" in result.stderr
