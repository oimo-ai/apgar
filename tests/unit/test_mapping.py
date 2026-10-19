from __future__ import annotations

from apgar.normalize.mapping import (
    CONTENT_KEYS,
    ENVIRONMENT_CHAIN,
    RELEASE_CHAIN,
    build_attribute_map,
)
from apgar.normalize.otlp import RawSpan


def _raw(**overrides: object) -> RawSpan:
    span = RawSpan(
        trace_id="11" * 16,
        span_id="aa" * 8,
        parent_span_id="",
        name="span",
        start_unix_nano=1,
        end_unix_nano=2,
        attributes={},
        status_code=0,
        status_message="",
        resource_attributes={},
    )
    for key, value in overrides.items():
        setattr(span, key, value)
    return span


def test_content_keys_never_stored() -> None:
    attributes = {key: "secret" for key in CONTENT_KEYS}
    attributes["gen_ai.agent.name"] = "billing"
    stored = build_attribute_map(_raw(attributes=attributes))
    assert "gen_ai.agent.name" in stored
    assert CONTENT_KEYS.isdisjoint(stored)


def test_resource_keys_prefixed() -> None:
    stored = build_attribute_map(
        _raw(resource_attributes={"service.name": "billing", "process.pid": "9"})
    )
    assert stored["resource.service.name"] == "billing"
    assert "resource.process.pid" not in stored
    assert "process.pid" not in stored


def test_resource_release_and_environment_chains_kept() -> None:
    resource = {key: "v1" for key in (*RELEASE_CHAIN, *ENVIRONMENT_CHAIN)}
    stored = build_attribute_map(_raw(resource_attributes=resource))
    assert stored == {f"resource.{key}": "v1" for key in resource}


def test_configured_keys_kept_on_span_and_resource() -> None:
    stored = build_attribute_map(
        _raw(
            attributes={"app.release": "span", "app.other": "x"},
            resource_attributes={"app.release": "resource", "app.other": "y"},
        ),
        frozenset({"app.release"}),
    )
    assert stored == {"app.release": "span", "resource.app.release": "resource"}


def test_configured_content_keys_still_dropped() -> None:
    content = {key: "secret" for key in CONTENT_KEYS}
    stored = build_attribute_map(
        _raw(attributes=content, resource_attributes=content), CONTENT_KEYS
    )
    assert stored == {}


def test_values_truncated_to_256() -> None:
    stored = build_attribute_map(_raw(attributes={"gen_ai.agent.name": "x" * 300}))
    assert len(stored["gen_ai.agent.name"]) == 256


def test_metadata_prefix_allowed() -> None:
    stored = build_attribute_map(
        _raw(attributes={"langfuse.trace.metadata.channel": "slack", "custom.secret": "no"})
    )
    assert stored["langfuse.trace.metadata.channel"] == "slack"
    assert "custom.secret" not in stored
