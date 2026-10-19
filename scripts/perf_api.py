"""Measure read-API latency and print it."""

from __future__ import annotations

import argparse
import math
import os
import platform
import subprocess
import time

import httpx
from repo_env import load_repo_env

_TARGETS = (
    "agents",
    "agent",
    "releases",
    "release",
)


def _machine() -> str:
    memory = "unknown memory"
    try:
        raw = subprocess.check_output(["sysctl", "-n", "hw.memsize"], text=True).strip()
        memory = f"{int(raw) / (1024**3):.1f} GiB"
    except (OSError, subprocess.CalledProcessError, ValueError):
        pass
    cpus = os.cpu_count() or 0
    return f"{platform.platform()}, {cpus} CPUs, {memory}"


def _percentile(values: list[float], pct: float) -> float:
    ordered = sorted(values)
    rank = math.ceil(pct / 100 * len(ordered)) - 1
    return ordered[min(len(ordered) - 1, max(0, rank))]


def _paths(agent: str, release: str) -> dict[str, str]:
    root = f"/api/v1/agents/{agent}"
    return {
        "agents": "/api/v1/agents",
        "agent": root,
        "releases": f"{root}/releases",
        "release": f"{root}/releases/{release}",
    }


def _latest_release(client: httpx.Client, base: str, token: str, agent: str) -> str:
    response = client.get(
        f"{base}/api/v1/agents/{agent}",
        headers={"Authorization": f"Bearer {token}"},
    )
    response.raise_for_status()
    body = response.json()
    latest = body.get("latest_release")
    if isinstance(latest, dict) and latest.get("release"):
        return str(latest["release"])
    listed = client.get(
        f"{base}/api/v1/agents/{agent}/releases",
        headers={"Authorization": f"Bearer {token}"},
    )
    listed.raise_for_status()
    items = listed.json().get("items", [])
    if not items:
        raise SystemExit(f"agent {agent} has no releases")
    return str(items[0]["release"])


def main() -> None:
    parser = argparse.ArgumentParser(description="Record API latency at the seeded volume.")
    parser.add_argument("--base", default="http://localhost:8000")
    parser.add_argument("--token", default="")
    parser.add_argument("--agent", default="perf-agent")
    parser.add_argument("--warmup", type=int, default=5)
    parser.add_argument("--requests", type=int, default=50)
    args = parser.parse_args()
    load_repo_env()
    token = args.token or os.environ.get("APGAR_ADMIN_TOKEN", "")
    if not token:
        raise SystemExit("missing --token or APGAR_ADMIN_TOKEN")
    base = args.base.rstrip("/")
    with httpx.Client(timeout=60.0) as client:
        release = _latest_release(client, base, token, args.agent)
        paths = _paths(args.agent, release)
        samples: dict[str, list[float]] = {name: [] for name in _TARGETS}
        headers = {"Authorization": f"Bearer {token}"}
        for name in _TARGETS:
            for index in range(args.warmup + args.requests):
                started = time.perf_counter()
                response = client.get(base + paths[name], headers=headers)
                elapsed_ms = (time.perf_counter() - started) * 1000
                response.raise_for_status()
                if index >= args.warmup:
                    samples[name].append(elapsed_ms)
    lines = [
        "## API latency at 1M turns",
        "",
        f"Machine: {_machine()}.",
        f"Agent `{args.agent}`, release `{release}`.",
        f"{args.requests} requests after {args.warmup} warm-up requests.",
        "p95 target: below 500 ms.",
        "",
        "| Endpoint | p50 ms | p95 ms |",
        "| --- | --- | --- |",
    ]
    gaps: list[str] = []
    for name in _TARGETS:
        p50 = _percentile(samples[name], 50)
        p95 = _percentile(samples[name], 95)
        lines.append(f"| `{paths[name]}` | {p50:.1f} | {p95:.1f} |")
        if p95 >= 500:
            gaps.append(f"`{paths[name]}` p95 {p95:.1f} ms exceeds 500 ms")
    if gaps:
        lines.extend(["", "Known gaps:", ""])
        lines.extend(f"* {item}" for item in gaps)
    else:
        lines.extend(["", "Every listed endpoint met the p95 target.", ""])
    print("\n".join(lines).rstrip())


if __name__ == "__main__":
    main()
