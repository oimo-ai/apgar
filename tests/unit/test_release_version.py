from __future__ import annotations

import importlib.util
import json
import shutil
import sys
from pathlib import Path
from types import ModuleType

import pytest

import apgar

ROOT = Path(__file__).resolve().parents[2]

COMPOSE = """\
services:
  clickhouse:
    image: clickhouse/clickhouse-server:25.8
  apgar-api:
    image: ghcr.io/oimo-ai/apgar:{apgar}
  apgar-worker:
    image: ghcr.io/oimo-ai/apgar:{apgar}
  apgar-ui:
    image: ghcr.io/oimo-ai/apgar-ui:{ui}
"""


def _script() -> ModuleType:
    path = ROOT / "scripts" / "release_version.py"
    spec = importlib.util.spec_from_file_location("release_version", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _repo(root: Path, version: str, apgar_image: str, ui_image: str) -> Path:
    (root / "apgar").mkdir(parents=True)
    (root / "ui").mkdir()
    (root / "pyproject.toml").write_text(f'[project]\nversion = "{version}"\n', encoding="utf-8")
    (root / "apgar" / "__init__.py").write_text(f'__version__ = "{version}"\n', encoding="utf-8")
    (root / "ui" / "package.json").write_text(json.dumps({"version": version}), encoding="utf-8")
    lock = {"version": version, "packages": {"": {"version": version}}}
    (root / "ui" / "package-lock.json").write_text(json.dumps(lock), encoding="utf-8")
    (root / "uv.lock").write_text(
        f'version = 1\n\n[[package]]\nname = "apgar"\nversion = "{version}"\n', encoding="utf-8"
    )
    chart = root / "deploy" / "helm" / "apgar" / "Chart.yaml"
    chart.parent.mkdir(parents=True)
    chart.write_text(
        f'apiVersion: v2\nname: apgar\nversion: {version}\nappVersion: "{version}"\n',
        encoding="utf-8",
    )
    compose = COMPOSE.format(apgar=apgar_image, ui=ui_image)
    (root / "docker-compose.yml").write_text(compose, encoding="utf-8")
    return root


def _copy_repo(script: ModuleType, root: Path) -> Path:
    for path in {place.path for place in script.PLACES}:
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / path, root / path)
    return root


def test_repository_agrees_on_its_version() -> None:
    script = _script()
    assert script.mismatches(script.parse_tag(f"v{apgar.__version__}"), ROOT) == []


def test_stable_and_prerelease_tags() -> None:
    script = _script()
    stable = script.parse_tag("v1.4.2")
    assert (stable.version, stable.core, stable.minor, stable.prerelease) == (
        "1.4.2",
        "1.4.2",
        "1.4",
        False,
    )
    candidate = script.parse_tag("v1.4.2-rc.1")
    assert (candidate.version, candidate.core, candidate.minor, candidate.prerelease) == (
        "1.4.2-rc.1",
        "1.4.2",
        "1.4",
        True,
    )


@pytest.mark.parametrize("tag", ["1.4.2", "v1.4", "v1.4.2+build.7", "v1.4.2-", "release-1"])
def test_rejects_malformed_tags(tag: str) -> None:
    with pytest.raises(ValueError):
        _script().parse_tag(tag)


def test_reports_every_place_that_disagrees(tmp_path: Path) -> None:
    script = _script()
    root = _repo(tmp_path, "0.2.0", "0.1.0", "0.2.0")
    (root / "ui" / "package.json").write_text(json.dumps({"version": "0.1.9"}), encoding="utf-8")
    lock = {"version": "0.2.0", "packages": {"": {"version": "0.1.9"}}}
    (root / "ui" / "package-lock.json").write_text(json.dumps(lock), encoding="utf-8")
    assert script.mismatches(script.parse_tag("v0.2.0"), root) == [
        "ui/package.json has 0.1.9, tag v0.2.0 needs 0.2.0",
        "ui/package-lock.json has 0.1.9, 0.2.0, tag v0.2.0 needs 0.2.0",
        "docker-compose.yml image apgar has 0.1.0, tag v0.2.0 needs 0.2.0",
    ]


def test_reports_places_that_are_missing(tmp_path: Path) -> None:
    script = _script()
    root = _repo(tmp_path, "0.2.0", "0.2.0", "0.2.0")
    (root / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")
    (root / "uv.lock").write_text("version = 1\n", encoding="utf-8")
    assert script.mismatches(script.parse_tag("v0.2.0"), root) == [
        "uv.lock has missing, tag v0.2.0 needs 0.2.0",
        "docker-compose.yml image apgar has missing, tag v0.2.0 needs 0.2.0",
        "docker-compose.yml image apgar-ui has missing, tag v0.2.0 needs 0.2.0",
    ]


def test_reports_a_chart_that_disagrees(tmp_path: Path) -> None:
    script = _script()
    root = _repo(tmp_path, "0.2.0", "0.2.0", "0.2.0")
    chart = root / "deploy" / "helm" / "apgar" / "Chart.yaml"
    chart.write_text('version: 0.2.0\nappVersion: "0.1.0"\n', encoding="utf-8")
    assert script.mismatches(script.parse_tag("v0.2.0"), root) == [
        "Chart.yaml appVersion has 0.1.0, tag v0.2.0 needs 0.2.0",
    ]


def test_render_pins_both_images_to_the_prerelease(tmp_path: Path) -> None:
    script = _script()
    root = _repo(tmp_path, "0.2.0", "0.2.0", "0.2.0")
    rendered = script.render_compose(script.parse_tag("v0.2.0-rc.1"), root)
    assert rendered == COMPOSE.format(apgar="0.2.0-rc.1", ui="0.2.0-rc.1")


def test_check_writes_compose_and_outputs(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    script = _script()
    root = _repo(tmp_path / "repo", "0.2.0", "0.2.0", "0.2.0")
    out = tmp_path / "docker-compose.yml"
    assert script.main(["check", "v0.2.0", "--compose", str(out)], root=root) == 0
    assert capsys.readouterr().out == "version=0.2.0\nminor=0.2\nprerelease=false\n"
    assert out.read_text(encoding="utf-8") == COMPOSE.format(apgar="0.2.0", ui="0.2.0")


def test_check_fails_without_writing(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    script = _script()
    root = _repo(tmp_path / "repo", "0.2.0", "0.2.0", "0.2.0")
    out = tmp_path / "docker-compose.yml"
    assert script.main(["check", "v0.3.0", "--compose", str(out)], root=root) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "pyproject.toml has 0.2.0, tag v0.3.0 needs 0.3.0" in captured.err
    assert not out.exists()
    assert script.main(["check", "0.2.0"], root=root) == 1
    assert "is not vX.Y.Z" in capsys.readouterr().err


def test_set_changes_only_the_version_lines(tmp_path: Path) -> None:
    script = _script()
    root = _copy_repo(script, tmp_path)
    script.set_version(script.parse_tag("v9.8.7"), root)
    assert script.mismatches(script.parse_tag("v9.8.7"), root) == []
    changed = 0
    for path in {place.path for place in script.PLACES}:
        before = (ROOT / path).read_text(encoding="utf-8").splitlines()
        after = (root / path).read_text(encoding="utf-8").splitlines()
        assert len(before) == len(after)
        for old, new in zip(before, after, strict=True):
            if old != new:
                assert new == old.replace(apgar.__version__, "9.8.7")
                changed += 1
    assert changed == 10


def test_set_keeps_the_prerelease_in_the_tag(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    script = _script()
    root = _repo(tmp_path, "0.1.0", "0.1.0", "0.1.0")
    assert script.main(["set", "0.2.0-rc.1"], root=root) == 0
    assert script.repository_versions(root) == dict.fromkeys(
        (place.name for place in script.PLACES), "0.2.0"
    )
    out = capsys.readouterr().out
    assert "Set 0.2.0 in pyproject.toml," in out
    assert "git tag v0.2.0-rc.1 && git push origin v0.2.0-rc.1" in out


def test_set_rejects_a_malformed_version(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    script = _script()
    root = _repo(tmp_path, "0.1.0", "0.1.0", "0.1.0")
    assert script.main(["set", "0.2"], root=root) == 1
    assert "version 0.2 is not X.Y.Z" in capsys.readouterr().err
    assert script.repository_versions(root)["pyproject.toml"] == "0.1.0"


def test_set_reports_a_place_it_cannot_write(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    script = _script()
    root = _repo(tmp_path, "0.1.0", "0.1.0", "0.1.0")
    (root / "uv.lock").write_text("version = 1\n", encoding="utf-8")
    assert script.main(["set", "0.2.0"], root=root) == 1
    assert "uv.lock has missing, tag v0.2.0 needs 0.2.0" in capsys.readouterr().err
