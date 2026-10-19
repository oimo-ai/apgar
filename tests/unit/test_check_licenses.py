from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[2]


def _policy() -> ModuleType:
    path = ROOT / "scripts" / "check_licenses.py"
    spec = importlib.util.spec_from_file_location("check_licenses", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_license_policy_on_sample_names() -> None:
    policy = _policy()
    assert policy.license_disposition("MIT") == "ok"
    assert policy.license_disposition("Apache-2.0") == "ok"
    assert policy.license_disposition("BSD-3-Clause") == "ok"
    assert policy.license_disposition("GPL-3.0-only") == "forbidden"
    assert policy.license_disposition("AGPL-3.0") == "forbidden"
    assert policy.license_disposition("GNU General Public License v3") == "forbidden"
    assert policy.license_disposition("LGPL-2.1-only") == "review"
    assert policy.license_disposition("GNU Lesser General Public License") == "review"
