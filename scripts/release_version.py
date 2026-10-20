"""Check a release tag against the repository and render the release Compose file.

A tag is vX.Y.Z or vX.Y.Z-PRERELEASE. X.Y.Z must match pyproject.toml,
apgar/__init__.py, ui/package.json, and both image tags in docker-compose.yml.
The rendered Compose file pins both images to the full version, prerelease included.
Prints version, minor, and prerelease as key=value lines for GITHUB_OUTPUT.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IMAGES = ("apgar", "apgar-ui")
TAG = re.compile(r"v(?P<core>(?P<minor>\d+\.\d+)\.\d+)(?P<pre>-[0-9A-Za-z][0-9A-Za-z.-]*)?")
IMAGE = re.compile(
    r"^(?P<ref>\s*image: ghcr\.io/oimo-ai/(?P<name>apgar|apgar-ui)):(?P<tag>\S+)$", re.MULTILINE
)
INIT_VERSION = re.compile(r'^__version__ = "(?P<version>[^"]+)"$', re.MULTILINE)


@dataclass(frozen=True, slots=True)
class Release:
    version: str
    core: str
    minor: str
    prerelease: bool


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
    pyproject = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    init = INIT_VERSION.search((root / "apgar" / "__init__.py").read_text(encoding="utf-8"))
    package = json.loads((root / "ui" / "package.json").read_text(encoding="utf-8"))
    found = {
        "pyproject.toml": str(pyproject["project"]["version"]),
        "apgar/__init__.py": init["version"] if init else "missing",
        "ui/package.json": str(package["version"]),
    }
    compose = (root / "docker-compose.yml").read_text(encoding="utf-8")
    for name in IMAGES:
        tags = sorted({m["tag"] for m in IMAGE.finditer(compose) if m["name"] == name})
        found[f"docker-compose.yml image {name}"] = ", ".join(tags) or "missing"
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


def main(argv: list[str] | None = None, root: Path = ROOT) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tag", help="git tag, for example v0.2.0 or v0.2.0-rc.1")
    parser.add_argument("--compose", type=Path, help="write the release Compose file here")
    args = parser.parse_args(argv)
    try:
        release = parse_tag(args.tag)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    errors = mismatches(release, root)
    for error in errors:
        print(f"error: {error}", file=sys.stderr)
    if errors:
        return 1
    if args.compose is not None:
        args.compose.write_text(render_compose(release, root), encoding="utf-8")
    print(f"version={release.version}")
    print(f"minor={release.minor}")
    print(f"prerelease={'true' if release.prerelease else 'false'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
