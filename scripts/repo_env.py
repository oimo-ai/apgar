"""Load the repository .env for host-side scripts."""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_repo_env() -> Path:
    path = ROOT / ".env"
    if path.exists():
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
    password = os.environ.get("CLICKHOUSE_PASSWORD", "")
    if password and not os.environ.get("APGAR_CLICKHOUSE_PASSWORD"):
        os.environ["APGAR_CLICKHOUSE_PASSWORD"] = password
    os.environ.setdefault("APGAR_CLICKHOUSE_URL", "http://localhost:8123")
    os.environ.setdefault("APGAR_CLICKHOUSE_USER", "apgar")
    os.environ.setdefault("APGAR_CLICKHOUSE_DATABASE", "apgar")
    return ROOT
