"""Check a release tag against the repository, or set the version for the next release.

check TAG [--compose PATH]
    TAG is vX.Y.Z or vX.Y.Z-PRERELEASE, and X.Y.Z must match every place in PLACES.
    Prints version, minor, and prerelease as key=value lines for GITHUB_OUTPUT.
    --compose writes docker-compose.yml with both images pinned to the full version.

set VERSION
    VERSION is X.Y.Z or X.Y.Z-PRERELEASE. Writes X.Y.Z to every place in PLACES and
    prints the tag to push. A prerelease suffix lives only in the tag.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tomllib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
TAG = re.compile(r"v(?P<core>(?P<minor>\d+\.\d+)\.\d+)(?P<pre>-[0-9A-Za-z][0-9A-Za-z.-]*)?")
IMAGE = re.compile(
    r"^(?P<ref>\s*image: ghcr\.io/oimo-ai/(?P<name>apgar|apgar-ui)):(?P<tag>\S+)$", re.MULTILINE
)
PYPROJECT_VERSION = re.compile(r'^version = "[^"]*"$', re.MULTILINE)
INIT_VERSION = re.compile(r'^__version__ = "(?P<version>[^"]*)"$', re.MULTILINE)
CHART = "deploy/helm/apgar/Chart.yaml"
CHART_VERSION = re.compile(r"^version: (?P<version>\S+)$", re.MULTILINE)
CHART_APP_VERSION = re.compile(r'^appVersion: "(?P<version>[^"]*)"$', re.MULTILINE)
LOCK_VERSION = re.compile(
    r'^(?P<head>\[\[package\]\]\nname = "apgar"\nversion = ")[^"]*"', re.MULTILINE
)


@dataclass(frozen=True, slots=True)
class Release:
    version: str
    core: str
    minor: str
    prerelease: bool


@dataclass(frozen=True, slots=True)
class Place:
    name: str
    path: str
    read: Callable[[str], list[str]]
    write: Callable[[str, str], str]


def _json(data: Any) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def _read_package_lock(text: str) -> list[str]:
    data = json.loads(text)
    return [str(data["version"]), str(data["packages"][""]["version"])]


def _write_package_lock(text: str, version: str) -> str:
    data = json.loads(text)
    data["version"] = version
    data["packages"][""]["version"] = version
    return _json(data)


def _write_package(text: str, version: str) -> str:
    data = json.loads(text)
    data["version"] = version
    return _json(data)


def _read_uv_lock(text: str) -> list[str]:
    packages = tomllib.loads(text).get("package", [])
    return [str(p["version"]) for p in packages if p.get("name") == "apgar"]


def _image_reader(name: str) -> Callable[[str], list[str]]:
    return lambda text: [m["tag"] for m in IMAGE.finditer(text) if m["name"] == name]


def _image_writer(name: str) -> Callable[[str, str], str]:
    def write(text: str, version: str) -> str:
        return IMAGE.sub(lambda m: f"{m['ref']}:{version}" if m["name"] == name else m[0], text)

    return write


PLACES = (
    Place(
        "pyproject.toml",
        "pyproject.toml",
        lambda text: [str(tomllib.loads(text)["project"]["version"])],
        lambda text, version: PYPROJECT_VERSION.sub(f'version = "{version}"', text, count=1),
    ),
    Place(
        "apgar/__init__.py",
        "apgar/__init__.py",
        lambda text: [m["version"] for m in INIT_VERSION.finditer(text)],
        lambda text, version: INIT_VERSION.sub(f'__version__ = "{version}"', text),
    ),
    Place(
        "ui/package.json",
        "ui/package.json",
        lambda text: [str(json.loads(text)["version"])],
        _write_package,
    ),
    Place("ui/package-lock.json", "ui/package-lock.json", _read_package_lock, _write_package_lock),
    Place(
        "uv.lock",
        "uv.lock",
        _read_uv_lock,
        lambda text, version: LOCK_VERSION.sub(lambda m: f'{m["head"]}{version}"', text),
    ),
    Place(
        "Chart.yaml version",
        CHART,
        lambda text: [m["version"] for m in CHART_VERSION.finditer(text)],
        lambda text, version: CHART_VERSION.sub(f"version: {version}", text),
    ),
    Place(
        "Chart.yaml appVersion",
        CHART,
        lambda text: [m["version"] for m in CHART_APP_VERSION.finditer(text)],
        lambda text, version: CHART_APP_VERSION.sub(f'appVersion: "{version}"', text),
    ),
    Place(
        "docker-compose.yml image apgar",
        "docker-compose.yml",
        _image_reader("apgar"),
        _image_writer("apgar"),
    ),
    Place(
        "docker-compose.yml image apgar-ui",
        "docker-compose.yml",
        _image_reader("apgar-ui"),
        _image_writer("apgar-ui"),
    ),
)


def parse_tag(tag: str) -> Release:
    match = TAG.fullmatch(tag)
    if match is None:
        raise ValueError(f"tag {tag} is not vX.Y.Z or vX.Y.Z-PRERELEASE")
    return Release(
        version=tag.removeprefix("v"),
        core=match["core"],
        minor=match["minor"],
        prerelease=match["pre"] is not None,
    )


def repository_versions(root: Path) -> dict[str, str]:
    """Version declared by each place that must match the release."""
    found = {}
    for place in PLACES:
        versions = sorted(set(place.read((root / place.path).read_text(encoding="utf-8"))))
        found[place.name] = ", ".join(versions) or "missing"
    return found


def mismatches(release: Release, root: Path) -> list[str]:
    return [
        f"{place} has {version}, tag v{release.version} needs {release.core}"
        for place, version in repository_versions(root).items()
        if version != release.core
    ]


def render_compose(release: Release, root: Path) -> str:
    compose = (root / "docker-compose.yml").read_text(encoding="utf-8")
    return IMAGE.sub(lambda m: f"{m['ref']}:{release.version}", compose)


def set_version(release: Release, root: Path) -> None:
    for place in PLACES:
        path = root / place.path
        text = path.read_text(encoding="utf-8")
        updated = place.write(text, release.core)
        if updated != text:
            path.write_text(updated, encoding="utf-8")


def _check(tag: str, compose: Path | None, root: Path) -> int:
    try:
        release = parse_tag(tag)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    errors = mismatches(release, root)
    for error in errors:
        print(f"error: {error}", file=sys.stderr)
    if errors:
        return 1
    if compose is not None:
        compose.write_text(render_compose(release, root), encoding="utf-8")
    print(f"version={release.version}")
    print(f"minor={release.minor}")
    print(f"prerelease={'true' if release.prerelease else 'false'}")
    return 0


def _set(version: str, root: Path) -> int:
    try:
        release = parse_tag(f"v{version.removeprefix('v')}")
    except ValueError:
        print(f"error: version {version} is not X.Y.Z or X.Y.Z-PRERELEASE", file=sys.stderr)
        return 1
    set_version(release, root)
    errors = mismatches(release, root)
    for error in errors:
        print(f"error: {error}", file=sys.stderr)
    if errors:
        return 1
    paths = ", ".join(dict.fromkeys(place.path for place in PLACES))
    print(f"Set {release.core} in {paths}.")
    print("After the change is merged, tag the commit on main:")
    print(f"  git tag v{release.version} && git push origin v{release.version}")
    return 0


def main(argv: list[str] | None = None, root: Path = ROOT) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser("check", help="check a tag and print the GitHub outputs")
    check.add_argument("tag", help="git tag, for example v0.2.0 or v0.2.0-rc.1")
    check.add_argument("--compose", type=Path, help="write the release Compose file here")
    write = commands.add_parser("set", help="write a version to every place")
    write.add_argument("version", help="X.Y.Z, or X.Y.Z-PRERELEASE to print a prerelease tag")
    args = parser.parse_args(argv)
    if args.command == "check":
        return _check(args.tag, args.compose, root)
    return _set(args.version, root)


if __name__ == "__main__":
    sys.exit(main())
