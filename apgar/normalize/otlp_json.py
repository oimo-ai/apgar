from __future__ import annotations

import base64
import json
from typing import Any

from google.protobuf.json_format import Parse, ParseError
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest

from apgar.normalize.otlp import MalformedPayload

_ID_FIELDS = ("traceId", "spanId", "parentSpanId", "trace_id", "span_id", "parent_span_id")


def _is_hex(value: str) -> bool:
    if len(value) % 2 != 0 or not value:
        return False
    return all(char in "0123456789abcdefABCDEF" for char in value)


def _convert_span(span: dict[str, Any]) -> None:
    for field in _ID_FIELDS:
        value = span.get(field)
        if not isinstance(value, str):
            continue
        if value == "":
            span.pop(field, None)
            continue
        if _is_hex(value):
            span[field] = base64.b64encode(bytes.fromhex(value)).decode("ascii")
    links = span.get("links")
    if isinstance(links, list):
        for link in links:
            if isinstance(link, dict):
                _convert_span(link)


def _convert_ids(document: dict[str, Any]) -> None:
    resources = document.get("resourceSpans")
    if not isinstance(resources, list):
        resources = document.get("resource_spans")
    if not isinstance(resources, list):
        return
    for resource in resources:
        if not isinstance(resource, dict):
            continue
        scopes = resource.get("scopeSpans")
        if not isinstance(scopes, list):
            scopes = resource.get("scope_spans")
        if not isinstance(scopes, list):
            continue
        for scope in scopes:
            if not isinstance(scope, dict):
                continue
            spans = scope.get("spans")
            if not isinstance(spans, list):
                continue
            for span in spans:
                if isinstance(span, dict):
                    _convert_span(span)


def parse(body: bytes) -> ExportTraceServiceRequest:
    try:
        parsed = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError, RecursionError) as exc:
        raise MalformedPayload("malformed json") from exc
    if not isinstance(parsed, dict):
        raise MalformedPayload("malformed json")
    _convert_ids(parsed)
    try:
        return Parse(
            json.dumps(parsed),
            ExportTraceServiceRequest(),
            ignore_unknown_fields=True,
        )
    except (ParseError, RecursionError) as exc:
        raise MalformedPayload("malformed otlp json") from exc
