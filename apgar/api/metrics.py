from __future__ import annotations

import os
import urllib.error
import urllib.request

from prometheus_client import Counter, Gauge, generate_latest

INGEST_REQUESTS = Counter(
    "apgar_ingest_requests_total",
    "OTLP ingest requests by result.",
    ["source_id", "status"],
)
INGEST_SPANS_RECEIVED = Counter(
    "apgar_ingest_spans_received_total",
    "Spans present in accepted ingest payloads.",
    ["source_id"],
)
INGEST_SPANS_ACCEPTED = Counter(
    "apgar_ingest_spans_accepted_total",
    "Spans stored by ingest.",
    ["source_id"],
)
INGEST_SPANS_DROPPED = Counter(
    "apgar_ingest_spans_dropped_total",
    "Spans dropped before storage.",
    ["source_id", "reason"],
)
INGEST_BYTES = Counter(
    "apgar_ingest_bytes_received_total",
    "Request body bytes received by ingest.",
    ["source_id"],
)
INGEST_STORAGE_ERRORS = Counter(
    "apgar_ingest_storage_errors_total",
    "Ingest requests that failed while writing storage.",
)
ASSEMBLY_ERRORS = Counter(
    "apgar_assembly_errors_total",
    "Traces the assembler failed to process.",
)
ASSEMBLY_LAG = Gauge(
    "apgar_assembly_lag_seconds",
    "Age of the oldest trace currently due for assembly.",
)
TURNS_ASSEMBLED = Counter(
    "apgar_turns_assembled_total",
    "Turns written by the assembler.",
    ["agent"],
)
TURNS_PARTIAL = Counter(
    "apgar_turns_partial_total",
    "Partial turns written by the assembler.",
    ["agent"],
)
TURNS_LATE = Counter(
    "apgar_turns_late_total",
    "Late turns written by the assembler.",
    ["agent"],
)
TURNS_DROPPED = Counter(
    "apgar_turns_dropped_total",
    "Traces dropped by the assembler.",
    ["reason"],
)
ROLLUP_LAG = Gauge(
    "apgar_rollup_lag_seconds",
    "Age of the rollup watermark at the start of the job.",
)

_WORKER_FAMILIES = ("apgar_turns_", "apgar_assembly_", "apgar_rollup_")


def _is_worker_family(line: str) -> bool:
    return any(name in line for name in _WORKER_FAMILIES)


def _local_metrics() -> bytes:
    payload = generate_latest()
    return payload if isinstance(payload, bytes) else str(payload).encode()


def _worker_metrics() -> bytes:
    url = os.environ.get("APGAR_WORKER_METRICS_URL", "")
    if not url:
        return b""
    try:
        with urllib.request.urlopen(url, timeout=2) as response:
            body = response.read()
    except (OSError, urllib.error.URLError, TimeoutError, ValueError):
        return b""
    return body if isinstance(body, bytes) else str(body).encode()


def merge_metrics(local: bytes, remote: bytes) -> bytes:
    local_lines = [line for line in local.decode().splitlines() if not _is_worker_family(line)]
    remote_lines = [
        line for line in remote.decode().splitlines() if line and _is_worker_family(line)
    ]
    lines = [*local_lines, *remote_lines]
    if not lines:
        return b""
    return ("\n".join(lines) + "\n").encode()


def render_metrics() -> bytes:
    # The worker records these families. The API only forwards them, when
    # APGAR_WORKER_METRICS_URL is set, so its own zero values never shadow the worker's.
    return merge_metrics(_local_metrics(), _worker_metrics())
