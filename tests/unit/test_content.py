from __future__ import annotations

import json

import pytest

from apgar.normalize.content import (
    extract_final_response,
    output_json_valid,
    parse_messages,
)


def test_genai_parts_last_assistant_message() -> None:
    value = [
        {"role": "assistant", "parts": [{"type": "text", "content": "first"}]},
        {"role": "user", "parts": [{"type": "text", "content": "middle"}]},
        {
            "role": "assistant",
            "parts": [
                {"type": "text", "content": "second"},
                {"type": "text", "content": "line"},
            ],
        },
    ]
    assert extract_final_response({"gen_ai.output.messages": value}) == "second\nline"


def test_openinference_plain_string() -> None:
    assert extract_final_response({"output.value": "plain answer"}) == "plain answer"


def test_messages_wrapper_object() -> None:
    wrapped = {"messages": [{"role": "assistant", "content": "wrapped"}]}
    assert parse_messages(wrapped) == [("assistant", "wrapped")]
    assert extract_final_response({"gen_ai.output.messages": wrapped}) == "wrapped"


def test_output_json_valid_cases() -> None:
    assert output_json_valid(None) is None
    assert output_json_valid(' {"ok":true} ') is True
    assert output_json_valid("not json") is False
    text = extract_final_response(
        {"gen_ai.output.messages": [{"role": "assistant", "content": '{"ok":true}'}]}
    )
    assert text == '{"ok":true}'
    assert output_json_valid(text) is True


def test_single_message_object_is_unwrapped() -> None:
    value = json.dumps({"role": "assistant", "content": "not json"})
    text = extract_final_response({"langfuse.observation.output": value})
    assert text == "not json"
    assert output_json_valid(text) is False
    assert parse_messages({"role": "assistant", "content": "plain"}) == [("assistant", "plain")]


def test_null_content_is_an_empty_reply() -> None:
    tool_only = {"role": "assistant", "content": None, "tool_calls": [{"id": "call_1"}]}
    assert parse_messages(tool_only) == [("assistant", "")]
    for value in (tool_only, json.dumps(tool_only), [tool_only]):
        text = extract_final_response({"langfuse.observation.output": value})
        assert text == ""
        assert output_json_valid(text) is False


@pytest.mark.parametrize(
    "attrs",
    [
        {"output.value": ""},
        {"langfuse.observation.output": ""},
        {"gen_ai.output.messages": [{"role": "assistant", "content": ""}]},
    ],
)
def test_empty_reply_is_counted_as_invalid(attrs: dict[str, object]) -> None:
    text = extract_final_response(attrs)
    assert text == ""
    assert output_json_valid(text) is False
