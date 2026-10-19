from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from apgar.domain.enums import (
    ConnectionType,
    Direction,
    MetricId,
    MetricRole,
    OutputFormat,
    Source,
    ToleranceMode,
)
from apgar.domain.settings import AgentFilter


class IngestTokenIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    agent: str | None = None
    auto_create_agents: bool = True


class LoginIn(BaseModel):
    token: str


class FromSpec(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    from_attribute: str | None = Field(default=None, alias="from")


class MetricIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool | None = None
    direction: Direction | None = None
    tolerance_mode: ToleranceMode | None = None
    tolerance: float | None = None
    role: MetricRole | None = None


class VerdictIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    min_turns: int | None = None
    min_sessions: int | None = None
    min_turns_slice: int | None = None
    fail_confirmations: int | None = None
    pass_confirmations: int | None = None
    max_window_hours: int | None = None
    include_mixed_sessions: bool | None = None
    alpha: float | None = None
    notify_healthy: bool | None = None


class AgentIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    source: Source
    langfuse_connection: str | None = None
    filter: AgentFilter | None = None
    environment: str | None = None
    release: FromSpec | None = None
    surface_mapping: FromSpec | None = None
    output_format: OutputFormat = OutputFormat.text
    slack_connection: str | None = None
    metrics: dict[str, MetricIn] | None = None
    verdict: VerdictIn | None = None


class AgentPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    langfuse_connection: str | None = None
    filter: AgentFilter | None = None
    environment: str | None = None
    release: FromSpec | None = None
    surface_mapping: FromSpec | None = None
    output_format: OutputFormat | None = None
    slack_connection: str | None = None
    metrics: dict[str, MetricIn] | None = None
    verdict: VerdictIn | None = None


class ConnectionIn(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    type: ConnectionType
    config: dict[str, object]


class ConnectionPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=128)
    config: dict[str, object] | None = None


class BaselineIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    release: str = Field(min_length=1, max_length=128)
    actor: str | None = None


class ExpectedChangesIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    metrics: list[MetricId]
    actor: str | None = None


class StopIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    actor: str | None = None
