"""License policy for Python and JavaScript dependencies."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def license_disposition(name: str) -> str:
    """Return ok, review, or forbidden.

    A name that contains GPL or AGPL is forbidden unless it also contains LGPL.
    The spelled out forms General Public License and Lesser General Public License
    are treated the same way. LGPL names are reported for review and do not fail
    the check.
    """
    folded = name.upper()
    if "LGPL" in folded or "LESSER GENERAL PUBLIC LICENSE" in folded:
        return "review"
    if "AGPL" in folded or "AFFERO GENERAL PUBLIC" in folded:
        return "forbidden"
    if "GPL" in folded or "GENERAL PUBLIC LICENSE" in folded:
        return "forbidden"
    return "ok"


def _names_from_python(rows: list[dict[str, object]]) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    for row in rows:
        package = str(row.get("Name", ""))
        license_name = str(row.get("License", ""))
        found.append((package, license_name))
    return found


def _names_from_javascript(document: dict[str, object]) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    for package, meta in document.items():
        if not isinstance(meta, dict):
            continue
        licenses = meta.get("licenses", "")
        if isinstance(licenses, list):
            text = ", ".join(str(item) for item in licenses)
        else:
            text = str(licenses)
        found.append((str(package), text))
    return found


def evaluate(pairs: list[tuple[str, str]]) -> tuple[list[str], list[str]]:
    forbidden: list[str] = []
    review: list[str] = []
    for package, name in pairs:
        disposition = license_disposition(name)
        line = f"{package}: {name}"
        if disposition == "forbidden":
            forbidden.append(line)
        elif disposition == "review":
            review.append(line)
    return forbidden, review


def render_markdown(
    python_rows: list[dict[str, object]],
    javascript_summary: str,
    javascript: list[tuple[str, str]],
    review: list[str],
) -> str:
    lines = [
        "# Licenses",
        "",
        "This file records the licenses of the dependencies used to build Apgar 0.1.0.",
        "The policy check fails when a license name contains GPL or AGPL and does not",
        "contain LGPL. LGPL names are listed under Needs review.",
        "",
        "## Python dependencies",
        "",
        "| Name | Version | License | URL |",
        "| --- | --- | --- | --- |",
    ]
    for row in python_rows:
        lines.append(
            "| {name} | {version} | {license} | {url} |".format(
                name=row.get("Name", ""),
                version=row.get("Version", ""),
                license=row.get("License", ""),
                url=row.get("URL", ""),
            )
        )
    lines.extend(
        [
            "",
            "## JavaScript dependencies",
            "",
            "### Summary",
            "",
            "```",
            javascript_summary.rstrip(),
            "```",
            "",
            "### Packages",
            "",
            "| Package | License |",
            "| --- | --- |",
        ]
    )
    for package, name in sorted(javascript):
        lines.append(f"| {package} | {name} |")
    lines.extend(["", "## Needs review", ""])
    if review:
        lines.extend(f"* {item}" for item in review)
    else:
        lines.append("None.")
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check dependency licenses.")
    parser.add_argument("--write", type=Path, default=None)
    args = parser.parse_args(argv)
    python_raw = subprocess.run(
        [
            "uv",
            "run",
            "--with",
            "pip-licenses",
            "pip-licenses",
            "--format=json",
            "--with-urls",
            "--order=license",
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    python_rows = json.loads(python_raw.stdout)
    if not isinstance(python_rows, list):
        print("pip-licenses did not return a list", file=sys.stderr)
        return 1
    summary = subprocess.run(
        ["npx", "--yes", "license-checker", "--production", "--summary"],
        cwd=ROOT / "ui",
        check=True,
        capture_output=True,
        text=True,
    )
    listing = subprocess.run(
        ["npx", "--yes", "license-checker", "--production", "--json"],
        cwd=ROOT / "ui",
        check=True,
        capture_output=True,
        text=True,
    )
    document = json.loads(listing.stdout)
    if not isinstance(document, dict):
        print("license-checker did not return an object", file=sys.stderr)
        return 1
    python_pairs = _names_from_python(python_rows)
    javascript_pairs = _names_from_javascript(document)
    forbidden, review = evaluate(python_pairs + javascript_pairs)
    if args.write is not None:
        args.write.write_text(
            render_markdown(python_rows, summary.stdout, javascript_pairs, review),
            encoding="utf-8",
        )
    if forbidden:
        print("forbidden licenses:", file=sys.stderr)
        for line in forbidden:
            print(line, file=sys.stderr)
        return 1
    if review:
        print("needs review:")
        for line in review:
            print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
