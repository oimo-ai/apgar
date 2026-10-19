from __future__ import annotations

from pathlib import Path

import yaml


def test_ci_workflow_has_expected_jobs() -> None:
    path = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "ci.yml"
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    jobs = set(document["jobs"])
    assert "python" in jobs
    assert "docker" in jobs
    assert "ui" in jobs


def test_release_workflow_has_image_and_release_jobs() -> None:
    path = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "release.yml"
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    jobs = set(document["jobs"])
    assert "images" in jobs
    assert "release" in jobs
