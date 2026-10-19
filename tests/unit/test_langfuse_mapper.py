from __future__ import annotations

import hashlib
from typing import Any

import pytest

from apgar.config import Settings
from apgar.connectors.langfuse.mapper import to_span_row
from apgar.domain.enums import SpanKind, SpanStatus
from apgar.domain.models import SpanRow
from apgar.normalize.normalizer import HmacKeys
from tests.factories import make_agent, make_connection
from tests.support import FIXTURE_NOW


def _row(
    settings: Settings,
    obs: dict[str, Any],
    root: dict[str, Any] | None = None,
) -> SpanRow:
    agent = make_agent(FIXTURE_NOW)
    connection = make_connection(FIXTURE_NOW)
    return to_span_row(
        obs,
        root or obs,
        agent,
        connection,
        HmacKeys.from_settings(settings),
        settings,
        FIXTURE_NOW,
    )


def test_id_normalization_and_root_parent(settings: Settings) -> None:
    root = {
        "id": "aaaaaaaaaaaaaaaa",
        "traceId": "ABCDEFABCDEFABCDEFABCDEFABCDEFAB",
        "type": "SPAN",
        "name": "billing",
        "startTime": "2026-10-08T08:00:00.000Z",
        "parentObservationId": "bbbbbbbbbbbbbbbb",
        "traceName": "billing-copilot",
        "release": "a1b2c3d",
    }
    span = _row(settings, root)
    assert span.trace_id == "abcdefabcdefabcdefabcdefabcdefab"
    assert span.span_id == "aaaaaaaaaaaaaaaa"
    assert span.parent_span_id == ""
    hashed = _row(
        settings,
        {
            "id": "cm1abc",
            "traceId": "not-hex",
            "type": "SPAN",
            "name": "billing",
            "startTime": "2026-10-08T08:00:00.000Z",
        },
    )
    assert hashed.span_id == hashlib.sha256(b"cm1abc").hexdigest()[:16]
    again = _row(
        settings,
        {
            "id": "cm1abc",
            "traceId": "not-hex",
            "type": "SPAN",
            "name": "billing",
            "startTime": "2026-10-08T08:00:00.000Z",
        },
    )
    assert again.span_id == hashed.span_id
    child = _row(
        settings,
        {
            "id": "cccccccccccccccc",
            "traceId": "abcdefabcdefabcdefabcdefabcdefab",
            "type": "EVENT",
            "name": "note",
            "startTime": "2026-10-08T08:00:01.000Z",
            "parentObservationId": "aaaaaaaaaaaaaaaa",
            "input": "hello",
            "output": '{"ok":true}',
        },
        root,
    )
    assert child.output_chars == len('{"ok":true}')


@pytest.mark.parametrize(
    ("kind", "root", "expected"),
    [
        ("AGENT", True, SpanKind.invoke_agent),
        ("SPAN", True, SpanKind.invoke_agent),
        ("CHAIN", True, SpanKind.invoke_workflow),
        ("GENERATION", False, SpanKind.chat),
        ("TOOL", False, SpanKind.execute_tool),
        ("RETRIEVER", False, SpanKind.retrieval),
        ("EVENT", False, SpanKind.other),
        ("EMBEDDING", False, SpanKind.other),
        ("GUARDRAIL", False, SpanKind.other),
        ("EVALUATOR", False, SpanKind.other),
        ("SPAN", False, SpanKind.other),
        ("CHAIN", False, SpanKind.other),
    ],
)
def test_type_mapping(settings: Settings, kind: str, root: bool, expected: SpanKind) -> None:
    obs = {
        "id": "aaaaaaaaaaaaaaaa" if root else "bbbbbbbbbbbbbbbb",
        "traceId": "11111111111111111111111111111111",
        "type": kind,
        "name": kind.lower(),
        "startTime": "2026-10-08T08:00:00.000Z",
    }
    parent = {
        "id": "aaaaaaaaaaaaaaaa",
        "traceId": obs["traceId"],
        "type": "SPAN",
        "name": "root",
        "startTime": "2026-10-08T08:00:00.000Z",
    }
    if not root:
        obs["parentObservationId"] = "aaaaaaaaaaaaaaaa"
    span = _row(settings, obs, obs if root else parent)
    assert span.kind is expected


def test_generation_error_counts_as_llm_error(settings: Settings) -> None:
    span = _row(
        settings,
        {
            "id": "aaaaaaaaaaaaaaaa",
            "traceId": "11111111111111111111111111111111",
            "type": "GENERATION",
            "name": "generation",
            "startTime": "2026-10-08T08:00:00.000Z",
            "level": "ERROR",
            "statusMessage": "provider down",
        },
    )
    assert span.kind is SpanKind.chat
    assert span.status is SpanStatus.error
    assert span.error_type == "provider down"
