from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError

from apgar.agent_config import AgentConfigError, build_agent
from apgar.config import Settings
from apgar.connection_config import ConnectionConfigError, config_material, parse_config
from apgar.domain.enums import ConnectionStatus, ConnectionType, OutputFormat, Source
from apgar.domain.models import Agent, Connection
from apgar.domain.settings import AgentFilter
from apgar.security import SecretBox
from apgar.storage.interfaces import MetaStore

_LOG = logging.getLogger("apgar.config")
_VAR = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


class ConfigError(Exception):
    pass


@dataclass(slots=True)
class ApplyResult:
    connections_created: int
    connections_updated: int
    agents_created: int
    agents_updated: int


class _FileModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int
    connections: dict[str, dict[str, Any]] = {}
    agents: dict[str, dict[str, Any]] = {}


def _substitute(value: Any, missing: set[str]) -> Any:
    if isinstance(value, str):

        def repl(match: re.Match[str]) -> str:
            name = match.group(1)
            if name not in os.environ:
                missing.add(name)
                return match.group(0)
            return os.environ[name]

        return _VAR.sub(repl, value)
    if isinstance(value, dict):
        return {str(key): _substitute(item, missing) for key, item in value.items()}
    if isinstance(value, list):
        return [_substitute(item, missing) for item in value]
    return value


def _snapshot(agent: Agent) -> dict[str, Any]:
    return {
        "source": agent.source.value,
        "langfuse_connection_id": agent.langfuse_connection_id,
        "filter": None if agent.filter is None else agent.filter.model_dump(mode="json"),
        "environment": agent.environment,
        "surface_from": agent.surface_mapping.from_attribute,
        "release_from": agent.release_settings.from_attribute,
        "metrics": agent.metric_settings,
        "verdict": agent.verdict_settings.model_dump(mode="json"),
        "output_format": agent.output_format.value,
        "slack_connection_id": agent.slack_connection_id,
    }


def _optional_str(value: Any) -> str | None:
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise ConfigError("expected a string")
    return value


async def apply(
    path: Path,
    settings: Settings,
    meta_store: MetaStore,
    box: SecretBox,
    now: datetime,
) -> ApplyResult:
    del box
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(f"invalid yaml: {exc}") from exc
    if not isinstance(loaded, dict):
        raise ConfigError("apgar.yaml must be a mapping")
    missing: set[str] = set()
    substituted = _substitute(loaded, missing)
    if missing:
        names = ", ".join(sorted(missing))
        raise ConfigError(f"missing environment variables: {names}")
    try:
        document = _FileModel.model_validate(substituted)
    except ValidationError as exc:
        raise ConfigError(str(exc.errors()[0]["msg"])) from exc
    if document.version != 1:
        raise ConfigError("version: must be 1")
    result = ApplyResult(0, 0, 0, 0)
    existing = {(item.name, item.type): item for item in await meta_store.list_connections()}
    for name, spec in document.connections.items():
        if "type" not in spec:
            raise ConfigError(f"connections.{name}: type is required")
        try:
            conn_type = ConnectionType(str(spec["type"]))
        except ValueError as exc:
            raise ConfigError(f"connections.{name}: unknown type") from exc
        fields = {key: value for key, value in spec.items() if key != "type"}
        current = existing.get((name, conn_type))
        try:
            config = parse_config(
                conn_type,
                fields,
                allow_insecure_slack=settings.allow_insecure_slack,
                previous=None if current is None else current.config,
            )
        except ConnectionConfigError as exc:
            raise ConfigError(f"connections.{name}: {exc}") from exc
        if current is None:
            created = Connection(
                id=str(uuid4()),
                name=name,
                type=conn_type,
                config=config,
                status=ConnectionStatus.untested,
                last_checked_at=None,
                last_error="",
                created_at=now,
                updated_at=now,
            )
            await meta_store.upsert_connection(created)
            existing[(name, conn_type)] = created
            result.connections_created += 1
            continue
        if config_material(current.config) != config_material(config):
            updated = replace(
                current,
                config=config,
                status=ConnectionStatus.untested,
                last_checked_at=None,
                last_error="",
                updated_at=now,
            )
            await meta_store.upsert_connection(updated)
            existing[(name, conn_type)] = updated
            result.connections_updated += 1

    def connection_id(connection_name: str, conn_type: ConnectionType) -> str:
        found = existing.get((connection_name, conn_type))
        if found is None:
            raise ConfigError(f"unknown connection: {connection_name}")
        return found.id

    for name, spec in document.agents.items():
        try:
            source = Source(str(spec.get("source")))
        except ValueError as exc:
            raise ConfigError(f"agents.{name}: source is invalid") from exc
        current_agent = await meta_store.get_agent_by_name(name)
        if current_agent is not None and current_agent.source is not source:
            raise ConfigError(f"agent {name} source cannot change")
        filt = spec.get("filter")
        try:
            agent_filter = None if filt is None else AgentFilter.model_validate(filt)
        except ValidationError as exc:
            raise ConfigError(f"agents.{name}: {exc.errors()[0]['msg']}") from exc
        release = spec.get("release") or {}
        surface = spec.get("surface_mapping") or {}
        if not isinstance(release, dict) or not isinstance(surface, dict):
            raise ConfigError(f"agents.{name}: release and surface_mapping must be mappings")
        langfuse_connection = None
        if spec.get("connection") is not None:
            langfuse_connection = connection_id(str(spec["connection"]), ConnectionType.langfuse)
        slack_connection = None
        if spec.get("slack") is not None:
            slack_connection = connection_id(str(spec["slack"]), ConnectionType.slack)
        output_raw = spec.get("output_format", "text")
        try:
            output_format = OutputFormat(str(output_raw))
        except ValueError as exc:
            raise ConfigError(f"agents.{name}: output_format is invalid") from exc
        verdict = spec.get("verdict")
        metrics = spec.get("metrics")
        if verdict is not None and not isinstance(verdict, dict):
            raise ConfigError(f"agents.{name}: verdict must be a mapping")
        if metrics is not None and not isinstance(metrics, dict):
            raise ConfigError(f"agents.{name}: metrics must be a mapping")
        try:
            desired = await build_agent(
                meta_store,
                name=name,
                source=source,
                langfuse_connection=langfuse_connection,
                agent_filter=agent_filter,
                environment=_optional_str(spec.get("environment")),
                release_from=_optional_str(release.get("from")),
                surface_from=_optional_str(surface.get("from")),
                output_format=output_format,
                slack_connection=slack_connection,
                metrics=metrics,
                verdict=verdict,
                now=now,
                existing=current_agent,
            )
        except AgentConfigError as exc:
            raise ConfigError(f"agents.{name}: {exc.message}") from exc
        if current_agent is None:
            await meta_store.upsert_agent(desired)
            result.agents_created += 1
            continue
        if _snapshot(current_agent) != _snapshot(desired):
            await meta_store.upsert_agent(desired)
            result.agents_updated += 1
    _LOG.info(
        "applied apgar.yaml: created %s connections, updated %s, created %s agents, updated %s",
        result.connections_created,
        result.connections_updated,
        result.agents_created,
        result.agents_updated,
    )
    return result
