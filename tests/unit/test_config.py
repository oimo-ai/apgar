from __future__ import annotations

import os

import pytest
from pydantic import ValidationError

from apgar.config import Settings, load_settings


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
    assert loaded.api_host == "0.0.0.0"
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
    assert loaded.evaluator_processes == max(1, (os.cpu_count() or 2) - 1)


def test_public_url_trailing_slash_stripped() -> None:
    loaded = Settings(
        secret_key="x" * 32,
        admin_token="y" * 16,
        public_url="http://localhost:8080/",
    )
    assert loaded.public_url == "http://localhost:8080"
