from __future__ import annotations

import json
from typing import Any

CHAT_ROLES = frozenset({"assistant", "user", "system", "tool", "developer", "model"})
MESSAGE_FIELDS = ("content", "parts", "tool_calls")


def _is_message(item: Any) -> bool:
    if not isinstance(item, dict):
        return False
    role = item.get("role")
    if not isinstance(role, str) or role.lower() not in CHAT_ROLES:
        return False
    return any(field in item for field in MESSAGE_FIELDS)


def parse_messages(value: Any) -> list[tuple[str, str | None]] | None:
    """Return (role, text) pairs, or None when the value is not a message list.

    An item counts as a message only when its role is a chat role and it has content,
    parts or tool_calls. A message with no readable text, such as a tool-call-only reply,
    has text None.
    """
    parsed = value
    if isinstance(parsed, str):
        try:
            parsed = json.loads(parsed)
        except json.JSONDecodeError:
            return None
    if isinstance(parsed, dict):
        if "messages" in parsed:
            parsed = parsed["messages"]
        elif _is_message(parsed):
            parsed = [parsed]
    if not isinstance(parsed, list):
        return None
    pairs: list[tuple[str, str | None]] = []
    for item in parsed:
        if not _is_message(item):
            return None
        pairs.append((item["role"], _message_text(item)))
    return pairs


def _message_text(item: dict[str, Any]) -> str | None:
    if "parts" in item:
        parts = item["parts"]
        if not isinstance(parts, list):
            return None
        chunks = [
            part["content"]
            for part in parts
            if isinstance(part, dict)
            and part.get("type") == "text"
            and isinstance(part.get("content"), str)
        ]
        return "\n".join(chunks) if chunks else None
    content = item.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        chunks = [
            part["text"]
            for part in content
            if isinstance(part, dict)
            and part.get("type") == "text"
            and isinstance(part.get("text"), str)
        ]
        return "\n".join(chunks) if chunks else None
    return None


def _extract(attrs: dict[str, Any], keys: tuple[str, ...], role: str) -> str | None:
    wanted = role.lower()
    saw_empty = False
    for key in keys:
        if key not in attrs:
            continue
        value = attrs[key]
        pairs = parse_messages(value)
        if pairs is not None:
            matches = [text for item_role, text in pairs if item_role.lower() == wanted]
            text = matches[-1] if matches else None
        elif isinstance(value, str):
            text = value
        else:
            text = None
        if text:
            return text
        if text == "":
            saw_empty = True
    return "" if saw_empty else None


def extract_final_response(attrs: dict[str, Any]) -> str | None:
    return _extract(
        attrs,
        ("gen_ai.output.messages", "output.value", "langfuse.observation.output"),
        "assistant",
    )


def output_chars(text: str | None) -> int | None:
    if text is None:
        return None
    return len(text)


def output_json_valid(text: str | None) -> bool | None:
    if text is None:
        return None
    try:
        json.loads(text.strip())
    except json.JSONDecodeError:
        return False
    return True
