"""Send OTLP/JSON batches and record achieved ingest throughput."""

from __future__ import annotations

import argparse
import asyncio
import math
import time
from typing import Any

import httpx
from repo_env import load_repo_env

_BATCH_SPANS = 100
_TRACES_PER_BATCH = 10


def _span(trace: str, span: str, parent: str | None, name: str, nano: int) -> dict[str, Any]:
    body: dict[str, Any] = {
        "traceId": trace,
        "spanId": span,
        "name": name,
        "startTimeUnixNano": str(nano),
        "endTimeUnixNano": str(nano + 1_000_000),
        "attributes": [
            {
                "key": "gen_ai.operation.name",
                "value": {"stringValue": "invoke_agent" if parent is None else "chat"},
            },
            {"key": "gen_ai.agent.name", "value": {"stringValue": "perf-ingest"}},
            {"key": "gen_ai.agent.version", "value": {"stringValue": "perf-ingest-1"}},
        ],
        "status": {"code": "STATUS_CODE_OK"},
    }
    if parent is not None:
        body["parentSpanId"] = parent
    return body


def _batch(sequence: int) -> dict[str, Any]:
    spans_per_trace = _BATCH_SPANS // _TRACES_PER_BATCH
    spans: list[dict[str, Any]] = []
    nano = 1_700_000_000_000_000_000 + sequence * 1_000_000_000
    for trace_index in range(_TRACES_PER_BATCH):
        trace = f"{(sequence * 16 + trace_index):032x}"
        root = f"{(sequence * 16 + trace_index):016x}"
        spans.append(_span(trace, root, None, "invoke_agent", nano))
        for child in range(1, spans_per_trace):
            span = f"{(sequence * 1000 + trace_index * 100 + child):016x}"
            spans.append(_span(trace, span, root, "chat", nano + child))
    return {"resourceSpans": [{"scopeSpans": [{"spans": spans}]}]}


def _percentile(values: list[float], pct: float) -> float:
    ordered = sorted(values)
    rank = math.ceil(pct / 100 * len(ordered)) - 1
    return ordered[min(len(ordered) - 1, max(0, rank))]


async def _drive(base: str, token: str, rate: int, seconds: int) -> dict[str, float]:
    interval = _BATCH_SPANS / rate
    deadline = time.perf_counter() + seconds
    latencies: list[float] = []
    non_200 = 0
    sent = 0
    next_at = time.perf_counter()
    sequence = 0
    inflight: set[asyncio.Task[None]] = set()
    limits = httpx.Limits(max_connections=100, max_keepalive_connections=50)

    async def post(client: httpx.AsyncClient, payload: dict[str, Any]) -> None:
        nonlocal non_200, sent
        started = time.perf_counter()
        response = await client.post(
            f"{base}/v1/traces",
            json=payload,
            headers={"Authorization": f"Bearer {token}"},
        )
        latencies.append((time.perf_counter() - started) * 1000)
        if response.status_code == 200:
            sent += _BATCH_SPANS
        else:
            non_200 += 1

    async with httpx.AsyncClient(timeout=30.0, limits=limits) as client:
        while time.perf_counter() < deadline:
            now = time.perf_counter()
            if now < next_at:
                await asyncio.sleep(next_at - now)
            next_at += interval
            task = asyncio.create_task(post(client, _batch(sequence)))
            inflight.add(task)
            task.add_done_callback(inflight.discard)
            sequence += 1
            if len(inflight) > 200:
                await asyncio.wait(inflight, return_when=asyncio.FIRST_COMPLETED)
        if inflight:
            await asyncio.gather(*inflight)
    elapsed = seconds
    achieved = sent / elapsed if elapsed else 0.0
    p95 = _percentile(latencies, 95) if latencies else 0.0
    return {
        "achieved": achieved,
        "p95_ms": p95,
        "non_200": float(non_200),
        "requests": float(sequence),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Load OTLP/JSON ingest.")
    parser.add_argument("--base", default="http://localhost:8000")
    parser.add_argument("--token", required=True)
    parser.add_argument("--rate", type=int, default=2000)
    parser.add_argument("--seconds", type=int, default=60)
    args = parser.parse_args()
    load_repo_env()
    result = asyncio.run(_drive(args.base.rstrip("/"), args.token, args.rate, args.seconds))
    gap = ""
    if result["achieved"] < args.rate or result["non_200"] > 0:
        gap = (
            "\n\nKnown gaps:\n\n"
            f"* achieved {result['achieved']:.0f} spans/s, "
            f"non-200 responses {int(result['non_200'])}. "
            "The target is 2,000 spans/s with zero non-200 responses."
        )
    body = (
        "## Ingest throughput\n\n"
        f"Target rate {args.rate} spans/s for {args.seconds} s. "
        "Each request is an OTLP/JSON batch of 100 spans (10 traces).\n\n"
        f"Achieved {result['achieved']:.0f} spans/s. "
        f"Request p95 {result['p95_ms']:.1f} ms. "
        f"Non-200 responses: {int(result['non_200'])}. "
        f"Requests sent: {int(result['requests'])}.\n\n"
        "Target: 2,000 spans per second, zero non-200 responses."
        f"{gap}\n"
    )
    print(body.rstrip())


if __name__ == "__main__":
    main()
