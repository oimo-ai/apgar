from __future__ import annotations

from typing import Any

from apgar.domain.enums import SpanKind

_GEN_AI = {
    "invoke_workflow": SpanKind.invoke_workflow,
    "invoke_agent": SpanKind.invoke_agent,
    "chat": SpanKind.chat,
    "generate_content": SpanKind.chat,
    "text_completion": SpanKind.chat,
    "execute_tool": SpanKind.execute_tool,
    "retrieval": SpanKind.retrieval,
}
_CONVENTION_KEYS = (
    "apgar.kind",
    "gen_ai.operation.name",
    "openinference.span.kind",
    "langfuse.observation.type",
)
_CHAT_HINTS = (
    "gen_ai.request.model",
    "gen_ai.usage.input_tokens",
    "llm.token_count.prompt",
    "llm.model_name",
)


def _present(attrs: dict[str, Any], key: str) -> bool:
    value = attrs.get(key)
    return value is not None and value != ""


def _openinference(kind: str, is_trace_root: bool) -> SpanKind:
    if kind == "AGENT":
        return SpanKind.invoke_agent
    if kind == "CHAIN":
        return SpanKind.invoke_workflow if is_trace_root else SpanKind.other
    if kind == "LLM":
        return SpanKind.chat
    if kind == "TOOL":
        return SpanKind.execute_tool
    if kind == "RETRIEVER":
        return SpanKind.retrieval
    return SpanKind.other


def _langfuse(kind: str, is_trace_root: bool) -> SpanKind:
    if kind == "agent":
        return SpanKind.invoke_agent
    if kind == "chain":
        return SpanKind.invoke_workflow if is_trace_root else SpanKind.other
    if kind == "generation":
        return SpanKind.chat
    if kind == "tool":
        return SpanKind.execute_tool
    if kind == "retriever":
        return SpanKind.retrieval
    if kind == "span":
        return SpanKind.invoke_agent if is_trace_root else SpanKind.other
    return SpanKind.other


def classify(attrs: dict[str, Any], is_trace_root: bool) -> SpanKind:
    if _present(attrs, "apgar.kind"):
        try:
            return SpanKind(str(attrs["apgar.kind"]))
        except ValueError:
            pass
    if _present(attrs, "gen_ai.operation.name"):
        return _GEN_AI.get(str(attrs["gen_ai.operation.name"]).lower(), SpanKind.other)
    if _present(attrs, "openinference.span.kind"):
        return _openinference(str(attrs["openinference.span.kind"]).upper(), is_trace_root)
    if _present(attrs, "langfuse.observation.type"):
        return _langfuse(str(attrs["langfuse.observation.type"]).lower(), is_trace_root)
    if not any(_present(attrs, key) for key in _CONVENTION_KEYS):
        if any(_present(attrs, key) for key in _CHAT_HINTS):
            return SpanKind.chat
        if _present(attrs, "gen_ai.tool.name") or _present(attrs, "tool.name"):
            return SpanKind.execute_tool
    return SpanKind.other
