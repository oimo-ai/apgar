from __future__ import annotations

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
