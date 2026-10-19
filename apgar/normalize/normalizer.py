from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from apgar.config import Settings
from apgar.domain.canonical import canonical_json
from apgar.domain.enums import Source, SpanKind, SpanStatus
from apgar.domain.models import SpanRow
from apgar.normalize.classify import classify
from apgar.normalize.content import extract_final_response, output_chars, output_json_valid
from apgar.normalize.mapping import (
    REQUEST_MODEL_CHAIN,
    RESPONSE_MODEL_CHAIN,
    TOOL_NAME_CHAIN,
    build_attribute_map,
)
from apgar.normalize.otlp import RawSpan
from apgar.security import derive_key, hmac_sha256

_ARGS_KEYS = ("gen_ai.tool.call.arguments", "input.value", "langfuse.observation.input")
_UINT64_MAX = (1 << 64) - 1


class MalformedSpan(Exception):
    pass


@dataclass(slots=True)
class HmacKeys:
    args_hash: bytes

    @classmethod
    def from_settings(cls, settings: Settings) -> HmacKeys:
        return cls(args_hash=derive_key(settings.secret_key, b"args-hash"))


def _timestamp(unix_nano: int) -> datetime:
    return datetime.fromtimestamp(unix_nano // 1_000_000 / 1000, UTC)


def _fit_uint(value: int) -> int | None:
    if value < 0 or value > _UINT64_MAX:
        return None
    return value


def _as_int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None or value == "":
        return None
    if isinstance(value, int):
        return _fit_uint(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            return None
        return _fit_uint(int(value))
    try:
        parsed = int(str(value))
    except (TypeError, ValueError):
        return None
    return _fit_uint(parsed)


def _as_float(value: Any) -> float | None:
    if isinstance(value, bool) or value is None or value == "":
        return None
    if isinstance(value, int | float):
        number = float(value)
        if not math.isfinite(number):
            return None
        return number
    try:
        number = float(str(value))
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def _json_object(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return None
    if isinstance(parsed, dict):
        return parsed
    return None


def _first_int(
    attrs: dict[str, Any],
    keys: tuple[str, ...],
    blob_key: str,
    field: str,
) -> int | None:
    for key in keys:
        if key not in attrs:
            continue
        parsed = _as_int(attrs[key])
        if parsed is not None:
            return parsed
    blob = _json_object(attrs.get(blob_key))
    if blob is None or field not in blob:
        return None
    return _as_int(blob[field])


def _first_float(
    attrs: dict[str, Any],
    keys: tuple[str, ...],
    blob_key: str,
    field: str,
) -> float | None:
    for key in keys:
        if key not in attrs:
            continue
        parsed = _as_float(attrs[key])
        if parsed is not None:
            return parsed
    blob = _json_object(attrs.get(blob_key))
    if blob is None or field not in blob:
        return None
    return _as_float(blob[field])


def _chain(attrs: dict[str, Any], keys: list[str]) -> str:
    for key in keys:
        value = attrs.get(key)
        if value is None or value == "":
            continue
        return str(value)[:256]
    return ""


def _args_hash(attrs: dict[str, Any], key: bytes) -> str:
    value: Any = None
    for name in _ARGS_KEYS:
        candidate = attrs.get(name)
        if candidate not in (None, ""):
            value = candidate
            break
    if value is None:
        return ""
    if isinstance(value, dict | list):
        return hmac_sha256(key, canonical_json(value)).hex()
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return hmac_sha256(key, value.encode("utf-8")).hex()
        return hmac_sha256(key, canonical_json(parsed)).hex()
    return ""


def _error_type(attrs: dict[str, Any], status_message: str) -> str:
    for key in ("error.type", "exception.type", "langfuse.observation.status_message"):
        value = attrs.get(key)
        if value not in (None, ""):
            return str(value)[:128]
    return status_message[:128]


def normalize(
    raw: RawSpan,
    *,
    source_id: str,
    source: Source,
    agent_hint: str,
    now: datetime,
    late_days: int,
    keys: HmacKeys,
    configured: frozenset[str] = frozenset(),
) -> SpanRow:
    if raw.start_unix_nano <= 0:
        raise MalformedSpan("invalid_timestamps")
    start_ts = _timestamp(raw.start_unix_nano)
    end_ts = _timestamp(raw.end_unix_nano)
    if end_ts < start_ts:
        end_ts = start_ts
    kind = classify(raw.attributes, raw.parent_span_id == "")
    level = str(raw.attributes.get("langfuse.observation.level", "")).upper()
    if raw.status_code == 2 or level == "ERROR":
        status = SpanStatus.error
    elif raw.status_code == 1:
        status = SpanStatus.ok
    else:
        status = SpanStatus.unset
    if status == SpanStatus.error:
        error_type = _error_type(raw.attributes, raw.status_message)
    else:
        error_type = ""
    request_model = _chain(raw.attributes, REQUEST_MODEL_CHAIN)
    response_model = _chain(raw.attributes, RESPONSE_MODEL_CHAIN)
    input_tokens = _first_int(
        raw.attributes,
        ("gen_ai.usage.input_tokens", "llm.token_count.prompt"),
        "langfuse.observation.usage_details",
        "input",
    )
    output_tokens = _first_int(
        raw.attributes,
        ("gen_ai.usage.output_tokens", "llm.token_count.completion"),
        "langfuse.observation.usage_details",
        "output",
    )
    cost = _first_float(
        raw.attributes,
        ("apgar.cost_usd", "gen_ai.usage.cost", "llm.cost.total"),
        "langfuse.observation.cost_details",
        "total",
    )
    if kind == SpanKind.execute_tool:
        tool_name = _chain(raw.attributes, TOOL_NAME_CHAIN) or raw.name
        tool_call_id = raw.span_id
        args_hash = _args_hash(raw.attributes, keys.args_hash)
    else:
        tool_name = ""
        tool_call_id = ""
        args_hash = ""
    final = extract_final_response(raw.attributes)
    return SpanRow(
        source_id=source_id,
        trace_id=raw.trace_id,
        span_id=raw.span_id,
        parent_span_id=raw.parent_span_id,
        kind=kind,
        name=raw.name,
        start_ts=start_ts,
        end_ts=end_ts,
        status=status,
        error_type=error_type,
        agent_hint=agent_hint,
        attributes=build_attribute_map(raw, configured),
        request_model=request_model,
        response_model=response_model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=cost,
        tool_name=tool_name,
        tool_call_id=tool_call_id,
        args_hash=args_hash,
        output_chars=output_chars(final),
        output_json_valid=output_json_valid(final),
        late=(now - start_ts) > timedelta(days=late_days),
        ingested_at=now,
    )
