from __future__ import annotations

import json
from typing import Any

from apgar.normalize.otlp import RawSpan

CONTENT_KEYS = frozenset(
    {
        "gen_ai.input.messages",
        "gen_ai.output.messages",
        "gen_ai.tool.call.arguments",
        "gen_ai.tool.call.result",
        "input.value",
        "output.value",
        "llm.input_messages",
        "llm.output_messages",
        "llm.prompts",
        "llm.completions",
        "langfuse.observation.input",
        "langfuse.observation.output",
    }
)
ALLOWLIST_SPAN_KEYS = frozenset(
    {
        "apgar.kind",
        "apgar.release",
        "apgar.environment",
        "apgar.session.id",
        "apgar.prompt.version",
        "apgar.surface",
        "apgar.cost_usd",
        "apgar.source",
        "langfuse.trace.id",
        "gen_ai.operation.name",
        "gen_ai.agent.name",
        "gen_ai.agent.version",
        "gen_ai.conversation.id",
        "gen_ai.prompt.name",
        "gen_ai.request.model",
        "gen_ai.response.model",
        "gen_ai.tool.name",
        "gen_ai.tool.call.id",
        "gen_ai.usage.input_tokens",
        "gen_ai.usage.output_tokens",
        "gen_ai.usage.cost",
        "agent.name",
        "session.id",
        "openinference.span.kind",
        "llm.model_name",
        "llm.request.model_name",
        "llm.response.model_name",
        "llm.token_count.prompt",
        "llm.token_count.completion",
        "llm.cost.total",
        "tool.name",
        "tool.id",
        "langfuse.trace.name",
        "langfuse.release",
        "langfuse.session.id",
        "langfuse.environment",
        "langfuse.prompt.name",
        "langfuse.prompt.version",
        "langfuse.observation.type",
        "langfuse.observation.model.name",
        "langfuse.observation.level",
        "langfuse.observation.status_message",
        "langfuse.observation.usage_details",
        "langfuse.observation.cost_details",
        "langfuse.trace.tags",
        "langfuse.user.id",
        "deployment.environment.name",
        "deployment.environment",
        "error.type",
        "exception.type",
    }
)
ALLOWLIST_SPAN_PREFIXES = ("langfuse.trace.metadata.", "langfuse.observation.metadata.")
RESOURCE_PREFIX = "resource."
MAX_ATTR_VALUE_CHARS = 256

AGENT_NAME_CHAIN = [
    "gen_ai.agent.name",
    "agent.name",
    "langfuse.trace.name",
    "resource.gen_ai.agent.name",
    "resource.service.name",
]
RELEASE_CHAIN = ["apgar.release", "gen_ai.agent.version", "langfuse.release"]
ENVIRONMENT_CHAIN = [
    "apgar.environment",
    "deployment.environment.name",
    "deployment.environment",
    "langfuse.environment",
]
ALLOWLIST_RESOURCE_KEYS = frozenset(
    {"service.name", "service.version", "gen_ai.agent.name", *RELEASE_CHAIN, *ENVIRONMENT_CHAIN}
)
SESSION_CHAIN = [
    "apgar.session.id",
    "gen_ai.conversation.id",
    "session.id",
    "langfuse.session.id",
]
REQUEST_MODEL_CHAIN = [
    "gen_ai.request.model",
    "llm.request.model_name",
    "llm.model_name",
    "langfuse.observation.model.name",
]
RESPONSE_MODEL_CHAIN = [
    "gen_ai.response.model",
    "llm.response.model_name",
    "llm.model_name",
    "langfuse.observation.model.name",
]
TOOL_NAME_CHAIN = ["gen_ai.tool.name", "tool.name"]


def attribute_to_string(value: Any) -> str:
    if isinstance(value, str):
        text = value
    elif isinstance(value, bool):
        text = "true" if value else "false"
    elif isinstance(value, int | float):
        text = str(value)
    elif isinstance(value, list | dict):
        text = json.dumps(value, separators=(",", ":"), ensure_ascii=False)
    else:
        text = str(value)
    return text[:MAX_ATTR_VALUE_CHARS]


def _allowed_span_key(key: str, configured: frozenset[str]) -> bool:
    if key in CONTENT_KEYS:
        return False
    if key in ALLOWLIST_SPAN_KEYS or key in configured:
        return True
    return key.startswith(ALLOWLIST_SPAN_PREFIXES)


def _allowed_resource_key(key: str, configured: frozenset[str]) -> bool:
    if key in CONTENT_KEYS:
        return False
    return key in ALLOWLIST_RESOURCE_KEYS or key in configured


def build_attribute_map(raw: RawSpan, configured: frozenset[str] = frozenset()) -> dict[str, str]:
    stored: dict[str, str] = {}
    for key, value in raw.attributes.items():
        if value is None or not _allowed_span_key(key, configured):
            continue
        stored[key] = attribute_to_string(value)
    for key, value in raw.resource_attributes.items():
        if value is None or not _allowed_resource_key(key, configured):
            continue
        stored[f"{RESOURCE_PREFIX}{key}"] = attribute_to_string(value)
    return stored
