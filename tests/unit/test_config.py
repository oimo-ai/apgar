from __future__ import annotations

import os
from pathlib import Path

import pytest
from pydantic import ValidationError

from apgar.config import Settings, available_cpus, cgroup_cpu_limit, load_settings


def _clear_apgar_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in list(os.environ):
        if key.startswith("APGAR_"):
            monkeypatch.delenv(key)


def test_missing_secret_key_exits_2(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _clear_apgar_env(monkeypatch)
    monkeypatch.setenv("APGAR_ADMIN_TOKEN", "admin-token-for-tests")
    with pytest.raises(SystemExit) as caught:
        load_settings()
    assert caught.value.code == 2
    assert (
        "config error: secret_key: APGAR_SECRET_KEY must be at least 32 characters"
        in capsys.readouterr().err
    )


def test_short_secret_key_rejected(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _clear_apgar_env(monkeypatch)
    monkeypatch.setenv("APGAR_SECRET_KEY", "short")
    monkeypatch.setenv("APGAR_ADMIN_TOKEN", "0123456789abcdef")
    with pytest.raises(SystemExit) as caught:
        load_settings()
    assert caught.value.code == 2
    assert (
        "config error: secret_key: APGAR_SECRET_KEY must be at least 32 characters"
        in capsys.readouterr().err
    )


def test_late_span_days_must_be_positive() -> None:
    with pytest.raises(ValidationError, match="late_span_days"):
        Settings(secret_key="x" * 32, admin_token="y" * 16, late_span_days=0)


def test_short_admin_token_rejected() -> None:
    with pytest.raises(ValidationError, match="APGAR_ADMIN_TOKEN must be at least 16 characters"):
        Settings(secret_key="x" * 32, admin_token="short")


def test_defaults_match_conventions(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_apgar_env(monkeypatch)
    loaded = Settings(secret_key="x" * 32, admin_token="y" * 16)
    assert loaded.clickhouse_url == "http://localhost:8123"
    assert loaded.clickhouse_user == "apgar"
    assert loaded.clickhouse_database == "apgar"
    assert loaded.api_host is None
    assert loaded.api_port == 8000
    assert loaded.public_url == "http://localhost:8080"
    assert loaded.log_level == "INFO"
    assert loaded.late_span_days == 7
    assert loaded.max_body_bytes == 33554432
    assert loaded.bootstrap_resamples == 10000
    assert loaded.worker_metrics_port == 8001
    assert loaded.assembly_quiet_seconds == 60
    assert loaded.bootstrap_chunk == 256
    assert loaded.telemetry == 1
    assert loaded.telemetry_endpoint == "https://us.i.posthog.com/i/v0/e/"
    assert loaded.evaluator_processes == max(1, available_cpus() - 1)
    assert loaded.clickhouse_ca_cert is None
    assert loaded.clickhouse_verify is True
    assert loaded.trusted_proxy_hops == 1


def test_empty_values_are_unset() -> None:
    loaded = Settings(secret_key="x" * 32, admin_token="y" * 16, clickhouse_ca_cert="", api_host="")
    assert loaded.clickhouse_ca_cert is None
    assert loaded.api_host is None


def test_trusted_proxy_hops_cannot_be_negative() -> None:
    with pytest.raises(ValidationError, match="trusted_proxy_hops"):
        Settings(secret_key="x" * 32, admin_token="y" * 16, trusted_proxy_hops=-1)


def _cgroup_v1(root: Path, quota: str, period: str) -> Path:
    (root / "cpu").mkdir()
    (root / "cpu" / "cpu.cfs_quota_us").write_text(quota, encoding="utf-8")
    (root / "cpu" / "cpu.cfs_period_us").write_text(period, encoding="utf-8")
    return root


@pytest.mark.parametrize(
    ("content", "expected"),
    [("200000 100000\n", 2.0), ("50000 100000\n", 0.5), ("max 100000\n", None)],
)
def test_cgroup_v2_cpu_limit(tmp_path: Path, content: str, expected: float | None) -> None:
    (tmp_path / "cpu.max").write_text(content, encoding="utf-8")
    assert cgroup_cpu_limit(tmp_path) == expected


def test_cgroup_v1_cpu_limit(tmp_path: Path) -> None:
    assert cgroup_cpu_limit(_cgroup_v1(tmp_path, "150000\n", "100000\n")) == 1.5


def test_cgroup_v1_without_quota_is_unlimited(tmp_path: Path) -> None:
    assert cgroup_cpu_limit(_cgroup_v1(tmp_path, "-1\n", "100000\n")) is None


def test_no_cgroup_files_is_unlimited(tmp_path: Path) -> None:
    assert cgroup_cpu_limit(tmp_path) is None


def test_available_cpus_follows_the_container_limit(tmp_path: Path) -> None:
    (tmp_path / "cpu.max").write_text("150000 100000\n", encoding="utf-8")
    assert available_cpus(tmp_path) == min(2, available_cpus(tmp_path / "missing"))
    (tmp_path / "cpu.max").write_text("10000 100000\n", encoding="utf-8")
    assert available_cpus(tmp_path) == 1


def test_available_cpus_without_a_limit_counts_usable_cpus(tmp_path: Path) -> None:
    expected = len(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else os.cpu_count()
    assert available_cpus(tmp_path) == expected


def test_public_url_trailing_slash_stripped() -> None:
    loaded = Settings(
        secret_key="x" * 32,
        admin_token="y" * 16,
        public_url="http://localhost:8080/",
    )
    assert loaded.public_url == "http://localhost:8080"
