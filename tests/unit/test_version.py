from __future__ import annotations

import json
import tomllib
from pathlib import Path

from apgar import __version__

ROOT = Path(__file__).resolve().parents[2]


def test_version_is_aligned() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    package = json.loads((ROOT / "ui" / "package.json").read_text(encoding="utf-8"))
    assert __version__ == "0.1.0"
    assert project["project"]["version"] == "0.1.0"
    assert package["version"] == "0.1.0"
