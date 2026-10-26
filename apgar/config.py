from __future__ import annotations

import math
import os
import sys
import uuid
from datetime import timedelta
from pathlib import Path
from typing import Any

from pydantic import Field, ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

EARLY_PERIOD = timedelta(hours=2)


CGROUP_ROOT = Path("/sys/fs/cgroup")


def cgroup_cpu_limit(root: Path = CGROUP_ROOT) -> float | None:
    """CPU limit of the container from cgroup v2 or v1, or None when it has none."""
    try:
        quota_text, period_text = (root / "cpu.max").read_text(encoding="utf-8").split()
        if quota_text == "max":
            return None
        quota, period = int(quota_text), int(period_text)
    except (OSError, ValueError):
        try:
            quota = int((root / "cpu" / "cpu.cfs_quota_us").read_text(encoding="utf-8"))
            period = int((root / "cpu" / "cpu.cfs_period_us").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
    if quota <= 0 or period <= 0:
        return None
    return quota / period


def available_cpus(root: Path = CGROUP_ROOT) -> int:
    # os.cpu_count() reports the host, so a container with a CPU limit would start
    # one evaluator process per host CPU.
    count = len(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else 0
    count = count or os.cpu_count() or 1
    limit = cgroup_cpu_limit(root)
    if limit is not None:
        count = min(count, max(1, math.ceil(limit)))
    return count


def _default_evaluator_processes() -> int:
    return max(1, available_cpus() - 1)


def _default_instance_id() -> str:
    return str(uuid.uuid4())


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="APGAR_", env_file=None, extra="ignore")

    clickhouse_url: str = "http://localhost:8123"
    clickhouse_user: str = "apgar"
    clickhouse_password: str = ""
    clickhouse_database: str = "apgar"
    clickhouse_ca_cert: str | None = None
    clickhouse_verify: bool = True
    secret_key: str = ""
    secret_key_previous: str | None = None
    admin_token: str = ""
    api_host: str | None = None
    api_port: int = 8000
    public_url: str = "http://localhost:8080"
    cookie_secure: bool = False
    trusted_proxy_hops: int = Field(default=1, ge=0)
    log_level: str = "INFO"
    late_span_days: int = Field(default=7, ge=1)
    max_body_bytes: int = 33554432
    telemetry: int = 1
    telemetry_endpoint: str = "https://us.i.posthog.com/i/v0/e/"
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

    @field_validator("secret_key_previous", "clickhouse_ca_cert", "api_host")
    @classmethod
    def _empty_is_unset(cls, value: str | None) -> str | None:
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
