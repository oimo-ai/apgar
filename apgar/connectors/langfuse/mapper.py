from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from typing import Any

from apgar.config import Settings
from apgar.domain.enums import Source
from apgar.domain.models import Agent, Connection, SpanRow
from apgar.domain.time import from_iso
from apgar.normalize.normalizer import HmacKeys, normalize
from apgar.normalize.otlp import RawSpan

_HEX_16 = re.compile(r"^[0-9a-f]{16}$")
_HEX_32 = re.compile(r"^[0-9a-f]{32}$")
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def _id16(value: str) -> str:
    lowered = value.lower()
    if _HEX_16.fullmatch(lowered):
        return lowered
    return hashlib.sha256(value.encode()).hexdigest()[:16]


def _id32(value: str) -> str:
    lowered = value.lower()
    if _HEX_32.fullmatch(lowered):
        return lowered
    return hashlib.sha256(value.encode()).hexdigest()[:32]


def _nano(value: datetime) -> int:
    delta = value.astimezone(UTC) - _EPOCH
    return (delta.days * 86_400 + delta.seconds) * 1_000_000_000 + delta.microseconds * 1_000


def _text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if value is None:
        return ""
    if isinstance(value, dict | list):
        return json.dumps(value, separators=(",", ":"), ensure_ascii=False)
    return str(value)


def _json_text(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False)


def to_span_row(
    obs: dict[str, Any],
    root: dict[str, Any],
    agent: Agent,
    connection: Connection,
    keys: HmacKeys,
    settings: Settings,
    ingest_now: datetime,
) -> SpanRow:
    original_trace = str(obs["traceId"])
    is_root = obs.get("id") == root.get("id")
    parent = obs.get("parentObservationId")
    parent_span_id = "" if is_root or parent is None else _id16(str(parent))
    start = from_iso(str(obs["startTime"]))
    end_raw = obs.get("endTime") or obs["startTime"]
    end = from_iso(str(end_raw))
    attributes: dict[str, Any] = {
        "langfuse.observation.type": str(obs["type"]),
        "langfuse.observation.level": str(obs.get("level") or ""),
        "langfuse.observation.status_message": str(obs.get("statusMessage") or ""),
        "langfuse.observation.usage_details": _json_text(obs.get("usageDetails") or {}),
        "apgar.source": "langfuse",
        "langfuse.trace.id": original_trace,
    }
    model = obs.get("model")
    if model:
        attributes["langfuse.observation.model.name"] = str(model)
    cost_details = obs.get("costDetails")
    if not cost_details and obs.get("totalCost") is not None:
        cost_details = {"total": obs["totalCost"]}
    attributes["langfuse.observation.cost_details"] = _json_text(cost_details or {})
    if obs.get("promptName"):
        attributes["langfuse.prompt.name"] = str(obs["promptName"])
    if obs.get("promptVersion") is not None:
        attributes["langfuse.prompt.version"] = str(obs["promptVersion"])
    if obs.get("sessionId"):
        attributes["langfuse.session.id"] = str(obs["sessionId"])
    if obs.get("environment"):
        attributes["langfuse.environment"] = str(obs["environment"])
    if obs.get("userId"):
        attributes["langfuse.user.id"] = str(obs["userId"])
    if root.get("traceName"):
        attributes["langfuse.trace.name"] = str(root["traceName"])
    if root.get("release"):
        attributes["langfuse.release"] = str(root["release"])
    attributes["langfuse.trace.tags"] = _json_text(root.get("tags") or [])
    metadata = root.get("metadata") or {}
    if isinstance(metadata, dict):
        for key, value in metadata.items():
            attributes[f"langfuse.trace.metadata.{key}"] = _text(value)
    if obs.get("input") is not None:
        attributes["langfuse.observation.input"] = _text(obs.get("input"))
    if obs.get("output") is not None:
        attributes["langfuse.observation.output"] = _text(obs.get("output"))
    level = str(obs.get("level") or "")
    raw = RawSpan(
        trace_id=_id32(original_trace),
        span_id=_id16(str(obs["id"])),
        parent_span_id=parent_span_id,
        name=str(obs.get("name") or obs["type"]),
        start_unix_nano=_nano(start),
        end_unix_nano=_nano(end),
        attributes=attributes,
        status_code=2 if level == "ERROR" else 0,
        status_message=str(obs.get("statusMessage") or ""),
        resource_attributes={},
    )
    return normalize(
        raw,
        source_id=connection.id,
        source=Source.langfuse,
        agent_hint=agent.id,
        now=ingest_now,
        late_days=settings.late_span_days,
        keys=keys,
    )
