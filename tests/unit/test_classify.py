from __future__ import annotations

import pytest

from apgar.domain.enums import SpanKind
from apgar.normalize.classify import classify


@pytest.mark.parametrize(
    ("attrs", "root", "expected"),
    [
        ({"apgar.kind": "chat"}, True, SpanKind.chat),
        ({"apgar.kind": "execute_tool"}, False, SpanKind.execute_tool),
        ({"gen_ai.operation.name": "invoke_workflow"}, False, SpanKind.invoke_workflow),
        ({"gen_ai.operation.name": "invoke_agent"}, False, SpanKind.invoke_agent),
        ({"gen_ai.operation.name": "chat"}, False, SpanKind.chat),
        ({"gen_ai.operation.name": "generate_content"}, False, SpanKind.chat),
        ({"gen_ai.operation.name": "text_completion"}, False, SpanKind.chat),
        ({"gen_ai.operation.name": "execute_tool"}, False, SpanKind.execute_tool),
        ({"gen_ai.operation.name": "retrieval"}, False, SpanKind.retrieval),
        ({"gen_ai.operation.name": "mystery"}, True, SpanKind.other),
        ({"openinference.span.kind": "AGENT"}, False, SpanKind.invoke_agent),
        ({"openinference.span.kind": "CHAIN"}, True, SpanKind.invoke_workflow),
        ({"openinference.span.kind": "CHAIN"}, False, SpanKind.other),
        ({"openinference.span.kind": "LLM"}, False, SpanKind.chat),
        ({"openinference.span.kind": "TOOL"}, False, SpanKind.execute_tool),
        ({"openinference.span.kind": "RETRIEVER"}, False, SpanKind.retrieval),
        ({"openinference.span.kind": "EMBEDDING"}, False, SpanKind.other),
        ({"langfuse.observation.type": "agent"}, False, SpanKind.invoke_agent),
        ({"langfuse.observation.type": "chain"}, True, SpanKind.invoke_workflow),
        ({"langfuse.observation.type": "chain"}, False, SpanKind.other),
        ({"langfuse.observation.type": "generation"}, False, SpanKind.chat),
        ({"langfuse.observation.type": "tool"}, False, SpanKind.execute_tool),
        ({"langfuse.observation.type": "retriever"}, False, SpanKind.retrieval),
        ({"langfuse.observation.type": "span"}, True, SpanKind.invoke_agent),
        ({"langfuse.observation.type": "span"}, False, SpanKind.other),
        ({"langfuse.observation.type": "event"}, True, SpanKind.other),
        ({"gen_ai.request.model": "gpt-4.1"}, False, SpanKind.chat),
        ({"gen_ai.usage.input_tokens": 3}, False, SpanKind.chat),
        ({"llm.token_count.prompt": 3}, False, SpanKind.chat),
        ({"llm.model_name": "gpt-4.1"}, False, SpanKind.chat),
        ({"gen_ai.tool.name": "sql_query"}, False, SpanKind.execute_tool),
        ({"tool.name": "sql_query"}, False, SpanKind.execute_tool),
        ({}, False, SpanKind.other),
        ({"apgar.kind": "not-a-kind", "gen_ai.operation.name": "chat"}, False, SpanKind.chat),
    ],
)
def test_classify_table(attrs: dict[str, object], root: bool, expected: SpanKind) -> None:
    assert classify(attrs, root) is expected
