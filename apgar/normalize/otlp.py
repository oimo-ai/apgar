from __future__ import annotations

import base64
import gzip
import zlib
from collections.abc import Iterator
from dataclasses import dataclass
from io import BytesIO
from typing import Any

from google.protobuf.message import DecodeError
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
from opentelemetry.proto.common.v1.common_pb2 import AnyValue


class MalformedPayload(Exception):
    pass


class PayloadTooLarge(Exception):
    pass


class UnsupportedMediaType(Exception):
    pass


@dataclass(slots=True)
class RawSpan:
    trace_id: str
    span_id: str
    parent_span_id: str
    name: str
    start_unix_nano: int
    end_unix_nano: int
    attributes: dict[str, Any]
    status_code: int
    status_message: str
    resource_attributes: dict[str, Any]


def _media_type(content_type: str) -> str:
    return content_type.split(";", 1)[0].strip().lower()


def decode_request(
    body: bytes,
    content_type: str,
    content_encoding: str | None,
    *,
    max_body_bytes: int | None = None,
) -> ExportTraceServiceRequest:
    payload = body
    if content_encoding and "gzip" in content_encoding.lower():
        try:
            with gzip.GzipFile(fileobj=BytesIO(body)) as stream:
                payload = (
                    stream.read() if max_body_bytes is None else stream.read(max_body_bytes + 1)
                )
        except (OSError, EOFError, zlib.error) as exc:
            raise MalformedPayload("invalid gzip") from exc
    if max_body_bytes is not None and len(payload) > max_body_bytes:
        raise PayloadTooLarge
    media = _media_type(content_type)
    if media == "application/x-protobuf":
        try:
            return ExportTraceServiceRequest.FromString(payload)
        except DecodeError as exc:
            raise MalformedPayload("malformed protobuf") from exc
    if media == "application/json":
        from apgar.normalize.otlp_json import parse

        return parse(payload)
    raise UnsupportedMediaType(media or "missing")


def any_value_to_python(value: AnyValue) -> Any:
    kind = value.WhichOneof("value")
    if kind is None:
        return None
    if kind == "string_value":
        return value.string_value
    if kind == "bool_value":
        return value.bool_value
    if kind == "int_value":
        return value.int_value
    if kind == "double_value":
        return value.double_value
    if kind == "bytes_value":
        return base64.b64encode(value.bytes_value).decode("ascii")
    if kind == "array_value":
        return [any_value_to_python(item) for item in value.array_value.values]
    if kind == "kvlist_value":
        return {item.key: any_value_to_python(item.value) for item in value.kvlist_value.values}
    return None


def _attributes(pairs: Any) -> dict[str, Any]:
    return {item.key: any_value_to_python(item.value) for item in pairs}


def iter_raw_spans(request: ExportTraceServiceRequest) -> Iterator[RawSpan]:
    for resource_spans in request.resource_spans:
        resource = _attributes(resource_spans.resource.attributes)
        for scope_spans in resource_spans.scope_spans:
            for span in scope_spans.spans:
                trace_id = span.trace_id.hex()
                span_id = span.span_id.hex()
                if (
                    len(trace_id) != 32
                    or len(span_id) != 16
                    or not any(span.trace_id)
                    or not any(span.span_id)
                    or (span.parent_span_id and len(span.parent_span_id) != 8)
                ):
                    trace_id = ""
                yield RawSpan(
                    trace_id=trace_id,
                    span_id=span_id,
                    parent_span_id=span.parent_span_id.hex(),
                    name=span.name,
                    start_unix_nano=int(span.start_time_unix_nano),
                    end_unix_nano=int(span.end_time_unix_nano),
                    attributes=_attributes(span.attributes),
                    status_code=int(span.status.code),
                    status_message=span.status.message,
                    resource_attributes=resource,
                )
