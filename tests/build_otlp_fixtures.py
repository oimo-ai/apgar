from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

BASE = datetime(2026, 10, 8, 9, 0, tzinfo=UTC)
OUT = Path(__file__).parent / "fixtures" / "otlp"


def _nano(moment: datetime) -> str:
    return str(int(moment.timestamp() * 1000) * 1_000_000)


def _s(key: str, value: str) -> dict[str, Any]:
    return {"key": key, "value": {"stringValue": value}}


def _i(key: str, value: int) -> dict[str, Any]:
    return {"key": key, "value": {"intValue": value}}


def _d(key: str, value: float) -> dict[str, Any]:
    return {"key": key, "value": {"doubleValue": value}}


def _messages(role: str, text: str) -> str:
    payload = [{"role": role, "parts": [{"type": "text", "content": text}]}]
    return json.dumps(payload, separators=(",", ":"))


def _span(
    trace_id: str,
    span_id: str,
    name: str,
    start: datetime,
    end: datetime,
    attributes: list[dict[str, Any]],
    *,
    parent: str | None = None,
    error: bool = False,
    message: str = "",
) -> dict[str, Any]:
    status: dict[str, Any] = {"code": "STATUS_CODE_ERROR" if error else "STATUS_CODE_OK"}
    if message:
        status["message"] = message
    span: dict[str, Any] = {
        "traceId": trace_id,
        "spanId": span_id,
        "name": name,
        "startTimeUnixNano": _nano(start),
        "endTimeUnixNano": _nano(end),
        "attributes": attributes,
        "status": status,
    }
    if parent:
        span["parentSpanId"] = parent
    return span


def _doc(*spans: dict[str, Any], resource: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {"scopeSpans": [{"spans": list(spans)}]}
    if resource:
        body["resource"] = {"attributes": resource}
    return {"resourceSpans": [body]}


def _at(seconds: float) -> datetime:
    return BASE + timedelta(seconds=seconds)


def _write(name: str, document: dict[str, Any]) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / name).write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    trace = "11111111111111111111111111111111"
    root = "aaaaaaaaaaaaaaaa"
    chat = "bbbbbbbbbbbbbbbb"
    tool = "cccccccccccccccc"
    user = _messages("user", "What is the balance?")
    assistant = _messages("assistant", "The balance is 42.")
    _write(
        "genai_basic.json",
        _doc(
            _span(
                trace,
                root,
                "invoke_agent",
                _at(0),
                _at(2.4),
                [
                    _s("gen_ai.operation.name", "invoke_agent"),
                    _s("gen_ai.agent.name", "billing-copilot"),
                    _s("gen_ai.agent.version", "a1b2c3d"),
                    _s("gen_ai.conversation.id", "s-1"),
                    _s("deployment.environment.name", "production"),
                    _s("gen_ai.input.messages", user),
                    _s("gen_ai.output.messages", assistant),
                ],
            ),
            _span(
                trace,
                chat,
                "chat",
                _at(0.1),
                _at(1),
                [
                    _s("gen_ai.operation.name", "chat"),
                    _s("gen_ai.request.model", "gpt-4.1"),
                    _s("gen_ai.response.model", "gpt-4.1"),
                    _i("gen_ai.usage.input_tokens", 900),
                    _i("gen_ai.usage.output_tokens", 150),
                    _d("gen_ai.usage.cost", 0.003),
                ],
                parent=root,
            ),
            _span(
                trace,
                tool,
                "sql_query",
                _at(1),
                _at(1.5),
                [
                    _s("gen_ai.operation.name", "execute_tool"),
                    _s("gen_ai.tool.name", "sql_query"),
                    _s("gen_ai.tool.call.arguments", json.dumps({"q": "select 1"})),
                ],
                parent=root,
            ),
        ),
    )
    retry_trace = "22222222222222222222222222222222"
    retry_root = "1212121212121212"
    sql_args = json.dumps({"q": "select 1"})
    invoice_args = json.dumps({"id": "Y"})
    retry_spans = [
        _span(
            retry_trace,
            retry_root,
            "invoke_agent",
            _at(0),
            _at(5),
            [
                _s("gen_ai.operation.name", "invoke_agent"),
                _s("gen_ai.agent.name", "billing-copilot"),
                _s("gen_ai.agent.version", "a1b2c3d"),
            ],
        )
    ]
    tools = [
        ("1313131313131313", 0.1, "sql_query", sql_args, True),
        ("1414141414141414", 0.4, "sql_query", sql_args, False),
        ("1515151515151515", 0.8, "get_invoice", invoice_args, False),
        ("1616161616161616", 1.2, "get_invoice", invoice_args, False),
        ("1717171717171717", 1.6, "get_invoice", invoice_args, False),
    ]
    for span_id, start, name, args, failed in tools:
        retry_spans.append(
            _span(
                retry_trace,
                span_id,
                name,
                _at(start),
                _at(start + 0.2),
                [
                    _s("gen_ai.operation.name", "execute_tool"),
                    _s("gen_ai.tool.name", name),
                    _s("gen_ai.tool.call.arguments", args),
                    *([_s("error.type", "ToolError")] if failed else []),
                ],
                parent=retry_root,
                error=failed,
            )
        )
    _write("genai_retry_loop.json", _doc(*retry_spans))
    no_args = "33333333333333333333333333333333"
    no_root = "2323232323232323"
    _write(
        "genai_no_args.json",
        _doc(
            _span(
                no_args,
                no_root,
                "invoke_agent",
                _at(0),
                _at(2),
                [
                    _s("gen_ai.operation.name", "invoke_agent"),
                    _s("gen_ai.agent.name", "billing-copilot"),
                ],
            ),
            _span(
                no_args,
                "2424242424242424",
                "sql_query",
                _at(0.2),
                _at(0.4),
                [_s("gen_ai.operation.name", "execute_tool"), _s("gen_ai.tool.name", "sql_query")],
                parent=no_root,
            ),
            _span(
                no_args,
                "2525252525252525",
                "sql_query",
                _at(0.5),
                _at(0.7),
                [_s("gen_ai.operation.name", "execute_tool"), _s("gen_ai.tool.name", "sql_query")],
                parent=no_root,
            ),
        ),
    )
    _write(
        "genai_no_cost.json",
        _doc(
            _span(
                "44444444444444444444444444444444",
                "3434343434343434",
                "invoke_agent",
                _at(0),
                _at(2),
                [
                    _s("gen_ai.operation.name", "invoke_agent"),
                    _s("gen_ai.agent.name", "billing-copilot"),
                    _s("gen_ai.agent.version", "a1b2c3d"),
                ],
            ),
            _span(
                "44444444444444444444444444444444",
                "3535353535353535",
                "chat",
                _at(0.1),
                _at(1),
                [
                    _s("gen_ai.operation.name", "chat"),
                    _s("gen_ai.response.model", "gpt-4.1-mini"),
                    _i("gen_ai.usage.input_tokens", 900),
                    _i("gen_ai.usage.output_tokens", 150),
                ],
                parent="3434343434343434",
            ),
        ),
    )
    _write(
        "openinference_basic.json",
        _doc(
            _span(
                "66666666666666666666666666666666",
                "5656565656565656",
                "agent",
                _at(0),
                _at(2),
                [
                    _s("openinference.span.kind", "AGENT"),
                    _s("agent.name", "billing-copilot"),
                    _s("session.id", "s-oi"),
                    _s("input.value", "What is the balance?"),
                    _s("output.value", "The balance is 42."),
                ],
            ),
            _span(
                "66666666666666666666666666666666",
                "5757575757575757",
                "llm",
                _at(0.1),
                _at(1),
                [
                    _s("openinference.span.kind", "LLM"),
                    _s("llm.model_name", "gpt-4.1"),
                    _i("llm.token_count.prompt", 900),
                    _i("llm.token_count.completion", 150),
                ],
                parent="5656565656565656",
            ),
            _span(
                "66666666666666666666666666666666",
                "5858585858585858",
                "tool",
                _at(1),
                _at(1.4),
                [
                    _s("openinference.span.kind", "TOOL"),
                    _s("tool.name", "sql_query"),
                    _s("input.value", json.dumps({"q": "select 1"})),
                ],
                parent="5656565656565656",
            ),
        ),
    )
    _write(
        "langfuse_otel_basic.json",
        _doc(
            _span(
                "77777777777777777777777777777777",
                "6767676767676767",
                "billing",
                _at(0),
                _at(2),
                [
                    _s("langfuse.observation.type", "span"),
                    _s("langfuse.trace.name", "billing-copilot"),
                    _s("langfuse.release", "a1b2c3d"),
                    _s("langfuse.session.id", "s-lf"),
                    _s("langfuse.environment", "production"),
                    _s("langfuse.prompt.name", "billing"),
                    _s("langfuse.prompt.version", "7"),
                ],
            ),
            _span(
                "77777777777777777777777777777777",
                "6868686868686868",
                "generation",
                _at(0.1),
                _at(1),
                [
                    _s("langfuse.observation.type", "generation"),
                    _s("langfuse.observation.model.name", "gpt-4.1"),
                    _s(
                        "langfuse.observation.usage_details",
                        json.dumps({"input": 900, "output": 150}),
                    ),
                    _s("langfuse.observation.cost_details", json.dumps({"total": 0.003})),
                ],
                parent="6767676767676767",
            ),
            _span(
                "77777777777777777777777777777777",
                "6969696969696969",
                "tool",
                _at(1),
                _at(1.3),
                [
                    _s("langfuse.observation.type", "tool"),
                    _s("gen_ai.tool.name", "sql_query"),
                    _s("gen_ai.tool.call.arguments", json.dumps({"q": "select 1"})),
                ],
                parent="6767676767676767",
            ),
        ),
    )
    nested = "88888888888888888888888888888888"
    workflow = "7878787878787878"
    agent_a = "7979797979797979"
    chat_a = "7a7a7a7a7a7a7a7a"
    agent_b = "7b7b7b7b7b7b7b7b"
    chat_b = "7c7c7c7c7c7c7c7c"
    _write(
        "nested_subagent.json",
        _doc(
            _span(
                nested,
                workflow,
                "workflow",
                _at(0),
                _at(4),
                [
                    _s("gen_ai.operation.name", "invoke_workflow"),
                    _s("gen_ai.agent.name", "billing-copilot"),
                    _s("gen_ai.agent.version", "a1b2c3d"),
                ],
            ),
            _span(
                nested,
                agent_a,
                "agent",
                _at(0.1),
                _at(2),
                [_s("gen_ai.operation.name", "invoke_agent")],
                parent=workflow,
            ),
            _span(
                nested,
                chat_a,
                "chat",
                _at(0.2),
                _at(1),
                [_s("gen_ai.operation.name", "chat"), _s("gen_ai.response.model", "gpt-4.1")],
                parent=agent_a,
            ),
            _span(
                nested,
                agent_b,
                "agent",
                _at(2),
                _at(3.5),
                [_s("gen_ai.operation.name", "invoke_agent")],
                parent=workflow,
            ),
            _span(
                nested,
                chat_b,
                "chat",
                _at(2.1),
                _at(3),
                [_s("gen_ai.operation.name", "chat"), _s("gen_ai.response.model", "gpt-4.1-mini")],
                parent=agent_b,
            ),
        ),
    )
    tops = "99999999999999999999999999999999"
    early = "8989898989898989"
    late = "8a8a8a8a8a8a8a8a"
    _write(
        "two_top_agents.json",
        _doc(
            _span(
                tops,
                early,
                "agent-early",
                _at(0),
                _at(2),
                [
                    _s("gen_ai.operation.name", "invoke_agent"),
                    _s("gen_ai.agent.name", "billing-copilot"),
                    _s("gen_ai.agent.version", "early"),
                ],
            ),
            _span(
                tops,
                "8b8b8b8b8b8b8b8b",
                "chat",
                _at(0.2),
                _at(1),
                [_s("gen_ai.operation.name", "chat")],
                parent=early,
            ),
            _span(
                tops,
                late,
                "agent-late",
                _at(3),
                _at(5),
                [
                    _s("gen_ai.operation.name", "invoke_agent"),
                    _s("gen_ai.agent.name", "billing-copilot"),
                    _s("gen_ai.agent.version", "late"),
                ],
            ),
            _span(
                tops,
                "8c8c8c8c8c8c8c8c",
                "chat",
                _at(3.2),
                _at(4),
                [_s("gen_ai.operation.name", "chat")],
                parent=late,
            ),
        ),
    )
    partial = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    _write(
        "partial_no_root.json",
        _doc(
            _span(
                partial,
                "9191919191919191",
                "chat-mid",
                _at(2),
                _at(3),
                [
                    _s("gen_ai.operation.name", "chat"),
                    _s("gen_ai.agent.name", "billing-copilot"),
                ],
                parent="ffffffffffffffff",
            ),
            _span(
                partial,
                "9292929292929292",
                "chat-early",
                _at(0),
                _at(1),
                [
                    _s("gen_ai.operation.name", "chat"),
                    _s("gen_ai.agent.name", "billing-copilot"),
                    _s("gen_ai.response.model", "gpt-4.1"),
                ],
                parent="eeeeeeeeeeeeeeee",
            ),
            _span(
                partial,
                "9393939393939393",
                "chat-late",
                _at(4),
                _at(5),
                [
                    _s("gen_ai.operation.name", "chat"),
                    _s("gen_ai.agent.name", "billing-copilot"),
                ],
                parent="dddddddddddddddd",
            ),
        ),
    )
    _write(
        "untagged.json",
        _doc(
            _span(
                "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
                "a1a1a1a1a1a1a1a1",
                "invoke_agent",
                _at(0),
                _at(1),
                [
                    _s("gen_ai.operation.name", "invoke_agent"),
                    _s("gen_ai.agent.name", "billing-copilot"),
                ],
            )
        ),
    )
    _write(
        "env_staging.json",
        _doc(
            _span(
                "cccccccccccccccccccccccccccccccc",
                "a2a2a2a2a2a2a2a2",
                "invoke_agent",
                _at(0),
                _at(1),
                [
                    _s("gen_ai.operation.name", "invoke_agent"),
                    _s("gen_ai.agent.name", "billing-copilot"),
                    _s("deployment.environment.name", "staging"),
                ],
            )
        ),
    )
    late_start = BASE - timedelta(days=8)
    _write(
        "late_span.json",
        _doc(
            _span(
                "dddddddddddddddddddddddddddddddd",
                "a3a3a3a3a3a3a3a3",
                "invoke_agent",
                late_start,
                late_start + timedelta(seconds=1),
                [
                    _s("gen_ai.operation.name", "invoke_agent"),
                    _s("gen_ai.agent.name", "billing-copilot"),
                    _s("gen_ai.agent.version", "old"),
                ],
            )
        ),
    )
    _write(
        "content_absent.json",
        _doc(
            _span(
                "eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee",
                "a4a4a4a4a4a4a4a4",
                "invoke_agent",
                _at(0),
                _at(1),
                [
                    _s("gen_ai.operation.name", "invoke_agent"),
                    _s("gen_ai.agent.name", "billing-copilot"),
                ],
            )
        ),
    )
    _write(
        "json_output.json",
        _doc(
            _span(
                "ffffffffffffffffffffffffffffffff",
                "a5a5a5a5a5a5a5a5",
                "invoke_agent",
                _at(0),
                _at(1),
                [
                    _s("gen_ai.operation.name", "invoke_agent"),
                    _s("gen_ai.agent.name", "support-agent"),
                    _s("gen_ai.output.messages", _messages("assistant", '{"ok":true}')),
                ],
            )
        ),
    )
    same = "0123456789abcdef0123456789abcdef"
    same_root = "ababcdcdababcdcd"
    _write(
        "reassembly_part1.json",
        _doc(
            _span(
                same,
                same_root,
                "invoke_agent",
                _at(0),
                _at(2),
                [
                    _s("gen_ai.operation.name", "invoke_agent"),
                    _s("gen_ai.agent.name", "billing-copilot"),
                    _s("gen_ai.agent.version", "a1b2c3d"),
                ],
            ),
            _span(
                same,
                "bcbcbcbcbcbcbcbc",
                "sql_query",
                _at(0.2),
                _at(0.5),
                [
                    _s("gen_ai.operation.name", "execute_tool"),
                    _s("gen_ai.tool.name", "sql_query"),
                    _s("gen_ai.tool.call.arguments", json.dumps({"q": "one"})),
                ],
                parent=same_root,
            ),
        ),
    )
    _write(
        "reassembly_part2.json",
        _doc(
            _span(
                same,
                "cdcdcdcdcdcdcdcd",
                "get_invoice",
                _at(0.6),
                _at(0.9),
                [
                    _s("gen_ai.operation.name", "execute_tool"),
                    _s("gen_ai.tool.name", "get_invoice"),
                    _s("gen_ai.tool.call.arguments", json.dumps({"q": "two"})),
                ],
                parent=same_root,
            )
        ),
    )
    _write(
        "surface_mapping.json",
        _doc(
            _span(
                "00112233445566778899aabbccddeeff",
                "ddeeff0011223344",
                "invoke_agent",
                _at(0),
                _at(1),
                [
                    _s("gen_ai.operation.name", "invoke_agent"),
                    _s("gen_ai.agent.name", "billing-copilot"),
                    _s("langfuse.trace.metadata.channel", "slack"),
                    _s("langfuse.trace.tags", json.dumps(["surface:web", "other"])),
                ],
            )
        ),
    )


if __name__ == "__main__":
    main()
