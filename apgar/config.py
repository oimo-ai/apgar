from __future__ import annotations

import os
import sys
import uuid
from datetime import timedelta
from typing import Any

from pydantic import Field, ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

EARLY_PERIOD = timedelta(hours=2)


def _default_evaluator_processes() -> int:
    return max(1, (os.cpu_count() or 2) - 1)


def _default_instance_id() -> str:
    return str(uuid.uuid4())


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="APGAR_", env_file=None, extra="ignore")

    clickhouse_url: str = "http://localhost:8123"
    clickhouse_user: str = "apgar"
    clickhouse_password: str = ""
    clickhouse_database: str = "apgar"
    secret_key: str = ""
    secret_key_previous: str | None = None
    admin_token: str = ""
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    public_url: str = "http://localhost:8080"
    cookie_secure: bool = False
    log_level: str = "INFO"
    late_span_days: int = Field(default=7, ge=1)
    max_body_bytes: int = 33554432
    telemetry: int = 1
    telemetry_endpoint: str = "https://us.i.posthog.com/i/v0/e/"
    config_file: str = "/etc/apgar/apgar.yaml"
    worker_instance_id: str = Field(default_factory=_default_instance_id)
    assembly_quiet_seconds: int = 60
    assembly_max_age_seconds: int = 600
    assembly_interval_seconds: int = 5
    rollup_interval_seconds: int = 300
    verdict_interval_seconds: int = 900
    verdict_early_interval_seconds: int = 300
    requests_interval_seconds: int = 5
    langfuse_sync_interval_seconds: int = 60
    evaluator_processes: int = Field(default_factory=_default_evaluator_processes)
    bootstrap_resamples: int = 10000
    bootstrap_chunk: int = 256
    worker_metrics_port: int = 8001
    allow_insecure_slack: bool = False

    def check_interval(self, release_age: timedelta) -> timedelta:
        seconds = self.verdict_interval_seconds
        if release_age < EARLY_PERIOD:
            seconds = min(seconds, self.verdict_early_interval_seconds)
        return timedelta(seconds=seconds)

    @field_validator("secret_key")
    @classmethod
    def _secret_key_length(cls, value: str) -> str:
        if len(value) < 32:
            raise ValueError("APGAR_SECRET_KEY must be at least 32 characters")
        return value

    @field_validator("admin_token")
    @classmethod
    def _admin_token_length(cls, value: str) -> str:
        if len(value) < 16:
            raise ValueError("APGAR_ADMIN_TOKEN must be at least 16 characters")
        return value

    @field_validator("public_url")
    @classmethod
    def _strip_one_trailing_slash(cls, value: str) -> str:
        if value.endswith("/"):
            return value[:-1]
        return value

    @field_validator("secret_key_previous")
    @classmethod
    def _empty_previous_is_unset(cls, value: str | None) -> str | None:
        if value == "":
            return None
        return value


def _message(error: Any) -> str:
    text = str(error.get("msg", "invalid configuration"))
    prefix = "Value error, "
    if text.startswith(prefix):
        return text[len(prefix) :]
    return text


def load_settings() -> Settings:
    try:
        return Settings()
    except ValidationError as exc:
        for error in exc.errors():
            loc = error.get("loc") or ("settings",)
            print(f"config error: {loc[0]}: {_message(error)}", file=sys.stderr)
        raise SystemExit(2) from exc
