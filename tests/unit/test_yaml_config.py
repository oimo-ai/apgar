from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from apgar.config import Settings
from apgar.security import SecretBox
from apgar.storage.memory import InMemoryMetaStore
from apgar.yaml_config import ConfigError, apply

_CONFIG = """\
version: 1
connections:
  langfuse-prod:
    type: langfuse
    host: https://cloud.langfuse.com
    public_key: ${LANGFUSE_PUBLIC_KEY}
    secret_key: ${LANGFUSE_SECRET_KEY}
  slack-alerts:
    type: slack
    webhook_url: ${SLACK_WEBHOOK_URL}
agents:
  billing-copilot:
    source: langfuse
    connection: langfuse-prod
    environment: production
    filter:
      trace_name: billing-copilot
    output_format: json
    slack: slack-alerts
    metrics:
      tool_error_rate: { tolerance: 0.02 }
  support-agent:
    source: otlp
    environment: production
"""


def _env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test")
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/services/x")


def _write(directory: Path, text: str = _CONFIG) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "apgar.yaml"
    path.write_text(text, encoding="utf-8")
    return path


async def test_env_substitution_applies_twice(
    settings: Settings, fixed_now: datetime, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _env(monkeypatch)
    path = _write(tmp_path)
    meta = InMemoryMetaStore(SecretBox(settings.secret_key, None))
    box = SecretBox(settings.secret_key, None)
    first = await apply(path, settings, meta, box, fixed_now)
    assert first.connections_created == 2
    assert first.agents_created == 2
    second = await apply(path, settings, meta, box, fixed_now)
    assert second.connections_created == 0
    assert second.connections_updated == 0
    assert second.agents_created == 0
    assert second.agents_updated == 0


async def test_missing_variable(settings: Settings, fixed_now: datetime, tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "version: 1\nconnections:\n  lf:\n    type: langfuse\n"
        "    host: https://x\n    public_key: ${MISSING_LF_KEY}\n    secret_key: secret\n",
    )
    meta = InMemoryMetaStore()
    with pytest.raises(ConfigError, match="MISSING_LF_KEY"):
        await apply(path, settings, meta, SecretBox(settings.secret_key, None), fixed_now)


async def test_update_on_changed_tolerance(
    settings: Settings, fixed_now: datetime, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _env(monkeypatch)
    meta = InMemoryMetaStore(SecretBox(settings.secret_key, None))
    box = SecretBox(settings.secret_key, None)
    await apply(_write(tmp_path), settings, meta, box, fixed_now)
    changed = _write(tmp_path / "changed", _CONFIG.replace("tolerance: 0.02", "tolerance: 0.03"))
    updated = await apply(changed, settings, meta, box, fixed_now)
    assert updated.agents_updated == 1
    agent = await meta.get_agent_by_name("billing-copilot")
    assert agent is not None
    assert agent.metric_settings["tool_error_rate"]["tolerance"] == 0.03


async def test_source_change_rejected(
    settings: Settings, fixed_now: datetime, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _env(monkeypatch)
    meta = InMemoryMetaStore(SecretBox(settings.secret_key, None))
    box = SecretBox(settings.secret_key, None)
    await apply(_write(tmp_path), settings, meta, box, fixed_now)
    changed = _write(
        tmp_path / "changed",
        _CONFIG.replace(
            "  support-agent:\n    source: otlp",
            "  support-agent:\n    source: langfuse",
        ),
    )
    with pytest.raises(ConfigError, match="source cannot change"):
        await apply(changed, settings, meta, box, fixed_now)


async def test_unknown_connection_type_is_rejected(
    settings: Settings, fixed_now: datetime, tmp_path: Path
) -> None:
    box = SecretBox(settings.secret_key, None)
    path = _write(tmp_path, "version: 1\nconnections:\n  other:\n    type: unknown\n")
    with pytest.raises(ConfigError, match=r"connections\.other: unknown type"):
        await apply(path, settings, InMemoryMetaStore(box), box, fixed_now)


async def test_unknown_verdict_field_is_rejected(
    settings: Settings, fixed_now: datetime, tmp_path: Path
) -> None:
    box = SecretBox(settings.secret_key, None)
    path = _write(
        tmp_path,
        "version: 1\nagents:\n  support-agent:\n    source: otlp\n"
        "    verdict:\n      max_mixed_share: 0.2\n",
    )
    with pytest.raises(ConfigError, match="verdict: unknown field max_mixed_share"):
        await apply(path, settings, InMemoryMetaStore(box), box, fixed_now)
