from __future__ import annotations

import base64
import gzip
import json

from google.protobuf.json_format import MessageToJson
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
from opentelemetry.proto.common.v1.common_pb2 import AnyValue, ArrayValue, KeyValue, KeyValueList

from apgar.normalize.otlp import (
    MalformedPayload,
    UnsupportedMediaType,
    any_value_to_python,
    decode_request,
    iter_raw_spans,
)
from tests.support import load_fixture


def test_json_hex_ids_parsed() -> None:
    decoded = decode_request(load_fixture("genai_basic.json"), "application/json", None)
    spans = list(iter_raw_spans(decoded))
    assert spans[0].trace_id == "1" * 32
    assert spans[0].span_id == "a" * 16
    assert spans[1].parent_span_id == "a" * 16


def test_json_snake_case_accepted() -> None:
    body = json.dumps(
        {
            "resource_spans": [
                {
                    "scope_spans": [
                        {
                            "spans": [
                                {
                                    "trace_id": "11" * 16,
                                    "span_id": "ab" * 8,
                                    "name": "snake",
                                    "start_time_unix_nano": "1000000000",
                                    "end_time_unix_nano": "2000000000",
                                }
                            ]
                        }
                    ]
                }
            ]
        }
    ).encode()
    spans = list(iter_raw_spans(decode_request(body, "application/json", None)))
    assert spans[0].name == "snake"
    assert spans[0].trace_id == "11" * 16


def test_protobuf_roundtrip() -> None:
    request = ExportTraceServiceRequest()
    span = request.resource_spans.add().scope_spans.add().spans.add()
    span.trace_id = bytes.fromhex("11" * 16)
    span.span_id = bytes.fromhex("ab" * 8)
    span.name = "proto"
    span.start_time_unix_nano = 1_000_000_000
    span.end_time_unix_nano = 2_000_000_000
    value = span.attributes.add()
    value.key = "gen_ai.agent.name"
    value.value.string_value = "billing-copilot"
    decoded = decode_request(request.SerializeToString(), "application/x-protobuf", None)
    spans = list(iter_raw_spans(decoded))
    assert spans[0].name == "proto"
    assert spans[0].attributes["gen_ai.agent.name"] == "billing-copilot"
    assert MessageToJson(decoded)


def test_gzip_decoded() -> None:
    body = gzip.compress(load_fixture("genai_basic.json"))
    spans = list(iter_raw_spans(decode_request(body, "application/json", "gzip")))
    assert len(spans) == 3


def test_invalid_gzip_is_malformed() -> None:
    try:
        decode_request(b"not-gzip", "application/json", "gzip")
    except MalformedPayload as exc:
        assert str(exc) == "invalid gzip"
    else:
        raise AssertionError("expected MalformedPayload")


def test_unsupported_media_type() -> None:
    try:
        decode_request(b"{}", "text/plain", None)
    except UnsupportedMediaType:
        return
    raise AssertionError("expected UnsupportedMediaType")


def test_invalid_id_length_yields_empty_trace_id() -> None:
    request = ExportTraceServiceRequest()
    span = request.resource_spans.add().scope_spans.add().spans.add()
    span.trace_id = b"\x01\x02"
    span.span_id = bytes.fromhex("ab" * 8)
    span.name = "bad"
    spans = list(iter_raw_spans(request))
    assert spans[0].trace_id == ""


def test_any_value_types() -> None:
    values = AnyValue()
    values.string_value = "s"
    assert any_value_to_python(values) == "s"
    flag = AnyValue(bool_value=True)
    assert any_value_to_python(flag) is True
    number = AnyValue(int_value=7)
    assert any_value_to_python(number) == 7
    decimal = AnyValue(double_value=1.5)
    assert any_value_to_python(decimal) == 1.5
    raw = AnyValue(bytes_value=b"\x00\xff")
    assert any_value_to_python(raw) == base64.b64encode(b"\x00\xff").decode("ascii")
    array = AnyValue(array_value=ArrayValue(values=[AnyValue(string_value="a")]))
    assert any_value_to_python(array) == ["a"]
    mapping = AnyValue(
        kvlist_value=KeyValueList(values=[KeyValue(key="k", value=AnyValue(string_value="v"))])
    )
    assert any_value_to_python(mapping) == {"k": "v"}
    assert any_value_to_python(AnyValue()) is None
