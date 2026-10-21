from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from apgar.config import Settings
from apgar.storage.memory import InMemoryEventStore, InMemoryMetaStore
from apgar.worker import main as worker_main
from apgar.worker.heartbeat import HEARTBEAT_KEY, write
from apgar.worker.main import run_worker
from apgar.yaml_config import ConfigError

_CONFIG = """\
version: 1
connections:
  slack-alerts:
    type: slack
    webhook_url: https://hooks.slack.com/services/x
agents:
  support-agent:
    source: otlp
    slack: slack-alerts
"""


@pytest.fixture(autouse=True)
def _no_jobs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(worker_main, "start_http_server", lambda port: None)
    monkeypatch.setattr(worker_main, "register_jobs", lambda *args: [])


def _with_config(settings: Settings, tmp_path: Path, text: str = _CONFIG) -> Settings:
    path = tmp_path / "apgar.yaml"
    path.write_text(text, encoding="utf-8")
    return settings.model_copy(update={"config_file": str(path)})


async def test_worker_applies_config_file_at_startup(
    settings: Settings,
    mem_stores: tuple[InMemoryEventStore, InMemoryMetaStore],
    fixed_now: datetime,
    tmp_path: Path,
) -> None:
    event_store, meta = mem_stores
    await run_worker(_with_config(settings, tmp_path), event_store, meta, lambda: fixed_now)
    agent = await meta.get_agent_by_name("support-agent")
    assert agent is not None
    connections = await meta.list_connections()
    assert [connection.name for connection in connections] == ["slack-alerts"]
    assert agent.slack_connection_id == connections[0].id
    assert await meta.get_setting("telemetry.config_file") == "1"


async def test_worker_records_missing_config_file(
    settings: Settings,
    mem_stores: tuple[InMemoryEventStore, InMemoryMetaStore],
    fixed_now: datetime,
    tmp_path: Path,
) -> None:
    event_store, meta = mem_stores
    missing = settings.model_copy(update={"config_file": str(tmp_path / "apgar.yaml")})
    await run_worker(missing, event_store, meta, lambda: fixed_now)
    assert await meta.get_setting("telemetry.config_file") == "0"


async def test_refused_worker_does_not_apply_config_file(
    settings: Settings,
    mem_stores: tuple[InMemoryEventStore, InMemoryMetaStore],
    fixed_now: datetime,
    tmp_path: Path,
) -> None:
    event_store, meta = mem_stores
    await write(meta, "other", fixed_now - timedelta(seconds=5))
    with pytest.raises(SystemExit) as caught:
        await run_worker(_with_config(settings, tmp_path), event_store, meta, lambda: fixed_now)
    assert caught.value.code == 1
    assert await meta.list_agents() == []
    assert await meta.list_connections() == []


async def test_config_error_stops_worker_before_heartbeat(
    settings: Settings,
    mem_stores: tuple[InMemoryEventStore, InMemoryMetaStore],
    fixed_now: datetime,
    tmp_path: Path,
) -> None:
    event_store, meta = mem_stores
    configured = _with_config(settings, tmp_path, "version: 2\n")
    with pytest.raises(ConfigError, match="version: must be 1"):
        await run_worker(configured, event_store, meta, lambda: fixed_now)
    assert await meta.get_setting(HEARTBEAT_KEY) is None
