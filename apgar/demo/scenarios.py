from __future__ import annotations

import hashlib
import json
import math
import random
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

import numpy as np

from apgar.domain.time import to_iso

BILLING = "billing-copilot"
SUPPORT = "support-agent"
_A2 = "fp-8e2f0c6a1b93"
_A3 = "fp-5a7d1e3f9c20"
_A4 = "fp-c4b2a9e8d711"
_B2 = "a1b2c3d"
_B3 = "b7c6d5e"
_B4 = "d4e5f6a"

RELEASE_WINDOWS: dict[str, tuple[tuple[str, float, float], ...]] = {
    BILLING: (
        ("fp-3c1e9a7b2d44", 0.0, 5.0),
        (_A2, 5.0, 8.5),
        ("fp-3c1e9a7b2d44", 8.5, 9.0),
        (_A3, 9.0, 12.0),
        (_A4, 12.0, 14.0),
    ),
    SUPPORT: (
        ("9f8e7d6", 0.0, 6.0),
        (_B2, 6.0, 11.0),
        (_B3, 11.0, 12.5),
        (_B4, 12.5, 14.0),
    ),
}
# US dollars per million input and output tokens, written on demo chat spans as gen_ai.usage.cost.
_PRICES: dict[str, tuple[float, float]] = {
    "gpt-4.1": (2.0, 8.0),
    "gpt-4.1-mini": (0.4, 1.6),
    "claude-sonnet-4": (3.0, 15.0),
}
_TOOLS: dict[str, tuple[str, ...]] = {
    BILLING: ("sql_query", "get_invoice", "send_email"),
    SUPPORT: ("search_kb", "create_ticket"),
}
_TOOL_WEIGHTS: dict[str, tuple[float, ...]] = {
    BILLING: (0.75, 0.15, 0.10),
    SUPPORT: (0.70, 0.30),
}
_SURFACES: dict[str, tuple[tuple[str, float], ...]] = {
    BILLING: (("slack", 0.50), ("web", 0.35), ("telegram", 0.15)),
    SUPPORT: (("web", 0.70), ("email", 0.30)),
}
_TOPICS = (
    "invoice total",
    "duplicate charge",
    "refund status",
    "payment method",
    "account balance",
    "overdue notice",
    "tax line",
    "credit memo",
    "billing address",
    "usage spike",
    "plan change",
    "failed payment",
    "receipt copy",
    "proration",
    "discount code",
    "seat count",
    "renewal date",
    "past due",
    "wire transfer",
    "card expiry",
    "dunning email",
    "credit balance",
    "invoice pdf",
    "late fee",
    "net terms",
    "quote revision",
    "subscription pause",
    "addon price",
    "currency conversion",
    "tax exemption",
    "partial payment",
    "chargeback",
    "billing contact",
    "po number",
    "usage export",
    "grace period",
    "annual prepay",
    "metered overage",
    "voided invoice",
    "closing balance",
)


def _hour_weight(hour: int) -> float:
    if 6 <= hour < 20:
        return 0.4 + 0.6 * math.sin(math.pi * (hour - 6) / 14.0)
    return 0.4


_HOUR_WEIGHTS = tuple(_hour_weight(hour) for hour in range(24))
_HOUR_SUM = sum(_HOUR_WEIGHTS)


@dataclass(slots=True)
class ToolPlan:
    name: str
    args: dict[str, Any]
    error: bool


@dataclass(slots=True)
class TurnPlan:
    agent: str
    release: str | None
    environment: str
    surface: str
    session_id: str
    turn_index: int
    start: datetime
    end: datetime
    user_text: str
    output_text: str
    model: str
    prompt_name: str
    prompt_version: str
    use_langfuse_prompt: bool
    input_tokens: int
    output_tokens: int
    tools: list[ToolPlan] = field(default_factory=list)
    llm_error: bool = False


def release_at(agent: str, fraction: float) -> str:
    windows = RELEASE_WINDOWS[agent]
    if fraction < windows[0][1]:
        return windows[0][0]
    for release, start, end in windows:
        if start <= fraction < end:
            return release
    return windows[-1][0]


def _fraction(moment: datetime, day0: datetime) -> float:
    return (moment - day0).total_seconds() / 86400.0


def _surface(rng: random.Random, agent: str) -> str:
    names = tuple(name for name, _weight in _SURFACES[agent])
    weights = tuple(weight for _name, weight in _SURFACES[agent])
    return _weighted(rng, names, weights)


def _weighted(rng: random.Random, items: tuple[str, ...], weights: tuple[float, ...]) -> str:
    pick = rng.random() * sum(weights)
    acc = 0.0
    for item, weight in zip(items, weights, strict=True):
        acc += weight
        if pick <= acc:
            return item
    return items[-1]


def _sample_hour(rng: random.Random) -> int:
    pick = rng.random() * _HOUR_SUM
    acc = 0.0
    for hour, weight in enumerate(_HOUR_WEIGHTS):
        acc += weight
        if pick <= acc:
            return hour
    return 23


def _sample_start(
    rng: random.Random,
    day0: datetime,
    days: int,
    latest_start: datetime,
) -> datetime:
    for _ in range(64):
        start = day0 + timedelta(
            days=rng.randrange(days),
            hours=_sample_hour(rng),
            seconds=rng.randrange(3600),
        )
        if day0 <= start <= latest_start:
            return start
    return day0 + timedelta(hours=1)


def _session_length(rng: random.Random) -> int:
    roll = rng.random()
    if roll < 0.60:
        return rng.randint(1, 5)
    if roll < 0.88:
        return rng.randint(6, 20)
    return rng.randint(21, 40)


def _lognormal(np_rng: np.random.Generator, median: float, sigma: float) -> float:
    return float(np_rng.lognormal(math.log(median), sigma))


def _error_probability(agent: str, release: str | None, tool: str) -> float:
    if agent == BILLING and release == _A2 and tool == "sql_query":
        return 0.09
    return 0.02


def _response_model(agent: str, fraction: float) -> str:
    if agent == BILLING and release_at(agent, fraction) == _A4 and fraction >= 13:
        return "gpt-4.1-mini"
    if agent == BILLING:
        return "gpt-4.1"
    return "claude-sonnet-4"


def _prompt(agent: str, fraction: float) -> tuple[str, str, bool]:
    if agent == BILLING:
        return "billing", "7", False
    if release_at(agent, fraction) == _B2 and fraction >= 8.5:
        return "support", "4", True
    return "support", "3", True


def _tools_for(
    rng: random.Random,
    np_rng: np.random.Generator,
    agent: str,
    release: str | None,
) -> list[ToolPlan]:
    count = min(6, int(np_rng.poisson(1.6)))
    if rng.random() < 0.15:
        count = 0
    injected = agent == SUPPORT and release == _B3
    loop = rng.random() < (0.10 if injected else 0.005)
    if loop:
        count = max(count, 3)
    names = _TOOLS[agent]
    weights = _TOOL_WEIGHTS[agent]
    loop_name = _weighted(rng, names, weights)
    if injected:
        loop_name = "search_kb"
    loop_args = {"n": 1, "q": "select 1"}
    calls: list[ToolPlan] = []
    for index in range(count):
        if loop and index < 3:
            name = loop_name
            args = dict(loop_args)
            failed = injected and index == 0
        else:
            name = _weighted(rng, names, weights)
            number = rng.randint(1, 9999)
            args = {"n": number, "q": f"select {number}"}
            failed = rng.random() < _error_probability(agent, release, name)
        calls.append(ToolPlan(name=name, args=args, error=failed))
        if failed and rng.random() < 0.5:
            calls.append(ToolPlan(name=name, args=dict(args), error=False))
    return calls


def _sentence(agent: str, index: int) -> str:
    topic = _TOPICS[index % len(_TOPICS)]
    if agent == BILLING:
        return f"Check the {topic} for this account"
    return f"Look up the {topic} for this customer"


def _build_session(
    rng: random.Random,
    np_rng: np.random.Generator,
    agent: str,
    day0: datetime,
    days: int,
    start: datetime,
    length: int,
    session_id: str,
    horizon: datetime,
    sentences: tuple[str, ...],
) -> list[TurnPlan]:
    cursor = start
    skeletons: list[tuple[datetime, float]] = []
    for _ in range(length):
        if cursor > horizon:
            break
        base_latency = _lognormal(np_rng, 2400, 0.5)
        skeletons.append((cursor, base_latency))
        rough_tools = 2
        rough = timedelta(milliseconds=base_latency + 400 * rough_tools)
        gap = math.exp(rng.uniform(math.log(30), math.log(600)))
        cursor = cursor + rough + timedelta(seconds=gap)
    if not skeletons:
        return []
    start_release = release_at(agent, _fraction(skeletons[0][0], day0))
    natural = [release_at(agent, _fraction(moment, day0)) for moment, _base in skeletons]
    crosses = any(release != start_release for release in natural)
    mixed = crosses and rng.random() < 0.05
    releases = natural if mixed else [start_release] * len(skeletons)
    turns: list[TurnPlan] = []
    for index, ((moment, base_latency), release) in enumerate(
        zip(skeletons, releases, strict=True),
        start=1,
    ):
        fraction = _fraction(moment, day0)
        if fraction >= days:
            fraction = days - 1e-6
        tools = _tools_for(rng, np_rng, agent, release)
        output_tokens = max(1, round(_lognormal(np_rng, 180, 0.6)))
        if release == _A3 and index > 20:
            output_tokens = max(1, int(output_tokens * 0.55))
        input_tokens = max(1, round(_lognormal(np_rng, 900, 0.3)))
        latency_ms = max(1, round(base_latency + 400 * len(tools)))
        end = moment + timedelta(milliseconds=latency_ms)
        user_text = f"{rng.choice(sentences)} {rng.randint(1, 9999)}"
        number = rng.randint(1, 9999)
        format_failure = agent == SUPPORT and rng.random() < 0.01
        if agent == SUPPORT:
            output_text = (
                "not-json"
                if format_failure
                else json.dumps(
                    {"ok": True, "n": number},
                    separators=(",", ":"),
                )
            )
        else:
            output_text = f"Completed request {number}."
        prompt_name, prompt_version, langfuse_prompt = _prompt(agent, fraction)
        turns.append(
            TurnPlan(
                agent=agent,
                release=release,
                environment="production",
                surface=_surface(rng, agent),
                session_id=session_id,
                turn_index=index,
                start=moment,
                end=end,
                user_text=user_text,
                output_text=output_text,
                model=_response_model(agent, fraction),
                prompt_name=prompt_name,
                prompt_version=prompt_version,
                use_langfuse_prompt=langfuse_prompt,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                tools=tools,
                llm_error=rng.random() < 0.005,
            )
        )
    return turns


def _mark_untagged(sessions: list[list[TurnPlan]]) -> None:
    turns = [turn for session in sessions for turn in session]
    target = round(0.08 * len(turns))
    remaining = list(sessions)
    picked = 0
    while remaining and picked < target:
        fitting = [session for session in remaining if picked + len(session) <= target]
        if not fitting:
            break
        fitting.sort(key=lambda session: (len(session), session[0].session_id))
        chosen = fitting[0]
        remaining.remove(chosen)
        for turn in chosen:
            turn.release = None
        picked += len(chosen)


def _mark_staging(turns: list[TurnPlan], rng: random.Random) -> None:
    count = round(0.03 * len(turns))
    indexes = list(range(len(turns)))
    rng.shuffle(indexes)
    for index in indexes[:count]:
        turns[index].environment = "staging"


def _schedule(
    rng: random.Random,
    np_rng: np.random.Generator,
    agent: str,
    days: int,
    turns_per_day: int,
    now: datetime,
) -> list[TurnPlan]:
    target = days * turns_per_day
    day0 = now - timedelta(days=days)
    latest_start = now - timedelta(hours=8)
    horizon = now - timedelta(seconds=120)
    sentences = tuple(_sentence(agent, index) for index in range(len(_TOPICS)))
    plans: list[TurnPlan] = []
    sessions: list[list[TurnPlan]] = []
    session_number = 0
    attempts = 0
    while len(plans) < target:
        attempts += 1
        if attempts > target * 5:
            raise RuntimeError("could not schedule demo turns")
        start = _sample_start(rng, day0, days, latest_start)
        length = min(_session_length(rng), target - len(plans))
        session_number += 1
        session = _build_session(
            rng,
            np_rng,
            agent,
            day0,
            days,
            start,
            length,
            f"s-{agent[:1]}-{session_number:06d}",
            horizon,
            sentences,
        )
        if not session:
            continue
        if len(plans) + len(session) > target:
            session = session[: target - len(plans)]
        plans.extend(session)
        sessions.append(session)
    if agent == SUPPORT:
        _mark_untagged(sessions)
        _mark_staging(plans, rng)
    return plans


def _nano(moment: datetime) -> str:
    return str(int(moment.timestamp() * 1000) * 1_000_000)


def _attr_string(key: str, value: str) -> dict[str, Any]:
    return {"key": key, "value": {"stringValue": value}}


def _attr_int(key: str, value: int) -> dict[str, Any]:
    return {"key": key, "value": {"intValue": value}}


def _attr_double(key: str, value: float) -> dict[str, Any]:
    return {"key": key, "value": {"doubleValue": value}}


def _messages(role: str, text: str) -> str:
    return json.dumps(
        [{"role": role, "parts": [{"type": "text", "content": text}]}],
        separators=(",", ":"),
        ensure_ascii=False,
    )


def _split(total: int, count: int) -> list[int]:
    if count <= 0:
        return []
    base, extra = divmod(total, count)
    parts = [base] * count
    parts[-1] += extra
    return parts


def _span(
    trace_id: str,
    span_id: str,
    parent_id: str | None,
    name: str,
    start: datetime,
    end: datetime,
    attributes: list[dict[str, Any]],
    error: bool,
) -> dict[str, Any]:
    span: dict[str, Any] = {
        "traceId": trace_id,
        "spanId": span_id,
        "name": name,
        "startTimeUnixNano": _nano(start),
        "endTimeUnixNano": _nano(end),
        "attributes": attributes,
        "status": {"code": "STATUS_CODE_ERROR" if error else "STATUS_CODE_OK"},
    }
    if parent_id:
        span["parentSpanId"] = parent_id
    return span


def _hex_id(seed: int, now: datetime, counter: int, size: int) -> str:
    raw = f"{seed}|{to_iso(now)}|{counter}".encode()
    return hashlib.sha256(raw).hexdigest()[:size]


def _request(turn: TurnPlan, seed: int, now: datetime, counter: list[int]) -> dict[str, Any]:
    def next_id(size: int) -> str:
        counter[0] += 1
        return _hex_id(seed, now, counter[0], size)

    trace_id = next_id(32)
    root_id = next_id(16)
    root_attrs = [
        _attr_string("gen_ai.operation.name", "invoke_agent"),
        _attr_string("gen_ai.agent.name", turn.agent),
        _attr_string("gen_ai.conversation.id", turn.session_id),
        _attr_string("deployment.environment.name", turn.environment),
        _attr_string("apgar.surface", turn.surface),
        _attr_string("gen_ai.input.messages", _messages("user", turn.user_text)),
        _attr_string("gen_ai.output.messages", _messages("assistant", turn.output_text)),
    ]
    if turn.release is not None:
        root_attrs.append(_attr_string("gen_ai.agent.version", turn.release))
    if turn.use_langfuse_prompt:
        root_attrs.append(_attr_string("langfuse.prompt.name", turn.prompt_name))
        root_attrs.append(_attr_string("langfuse.prompt.version", turn.prompt_version))
    else:
        prompt = f"{turn.prompt_name}@{turn.prompt_version}"
        root_attrs.append(_attr_string("gen_ai.prompt.name", prompt))
    chats = len(turn.tools) + 1
    input_parts = _split(turn.input_tokens, chats)
    output_parts = _split(turn.output_tokens, chats)
    price = _PRICES[turn.model]
    children: list[dict[str, Any]] = []
    pieces = max(chats + len(turn.tools), 1)
    duration_ms = (turn.end - turn.start).total_seconds() * 1000
    slot = max(1, int(duration_ms / pieces))
    cursor = turn.start

    def advance() -> tuple[datetime, datetime]:
        nonlocal cursor
        child_end = cursor + timedelta(milliseconds=slot)
        bounds = (cursor, child_end)
        cursor = child_end
        return bounds

    for index, tool in enumerate(turn.tools):
        chat_start, chat_end = advance()
        children.append(
            _chat_span(
                trace_id,
                next_id(16),
                root_id,
                turn,
                chat_start,
                chat_end,
                input_parts[index],
                output_parts[index],
                price,
                False,
            )
        )
        tool_start, tool_end = advance()
        children.append(
            _span(
                trace_id,
                next_id(16),
                root_id,
                tool.name,
                tool_start,
                tool_end,
                [
                    _attr_string("gen_ai.operation.name", "execute_tool"),
                    _attr_string("gen_ai.tool.name", tool.name),
                    _attr_string(
                        "gen_ai.tool.call.arguments",
                        json.dumps(tool.args, separators=(",", ":"), sort_keys=True),
                    ),
                    *([_attr_string("error.type", "ToolError")] if tool.error else []),
                ],
                tool.error,
            )
        )
    final_start, final_end = advance()
    children.append(
        _chat_span(
            trace_id,
            next_id(16),
            root_id,
            turn,
            final_start,
            final_end,
            input_parts[-1],
            output_parts[-1],
            price,
            turn.llm_error,
        )
    )
    root = _span(trace_id, root_id, None, "invoke_agent", turn.start, turn.end, root_attrs, False)
    return {
        "resourceSpans": [
            {
                "resource": {"attributes": [_attr_string("service.name", turn.agent)]},
                "scopeSpans": [{"spans": [root, *children]}],
            }
        ]
    }


def _chat_span(
    trace_id: str,
    span_id: str,
    parent_id: str,
    turn: TurnPlan,
    start: datetime,
    end: datetime,
    input_tokens: int,
    output_tokens: int,
    price: tuple[float, float],
    error: bool,
) -> dict[str, Any]:
    cost = input_tokens / 1e6 * price[0] + output_tokens / 1e6 * price[1]
    attributes = [
        _attr_string("gen_ai.operation.name", "chat"),
        _attr_string("gen_ai.request.model", turn.model),
        _attr_string("gen_ai.response.model", turn.model),
        _attr_int("gen_ai.usage.input_tokens", input_tokens),
        _attr_int("gen_ai.usage.output_tokens", output_tokens),
        _attr_double("gen_ai.usage.cost", cost),
    ]
    if error:
        attributes.append(_attr_string("error.type", "LLMError"))
    return _span(trace_id, span_id, parent_id, "chat", start, end, attributes, error)


def generate(
    days: int,
    turns_per_day: int,
    seed: int,
    now: datetime,
) -> Iterator[tuple[datetime, dict[str, Any]]]:
    rng = random.Random(seed)
    np_rng = np.random.default_rng(seed)
    counter = [0]
    for agent in (BILLING, SUPPORT):
        for turn in _schedule(rng, np_rng, agent, days, turns_per_day, now):
            yield turn.end + timedelta(seconds=5), _request(turn, seed, now, counter)
