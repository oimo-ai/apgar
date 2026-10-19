from __future__ import annotations

import hashlib
import logging
from collections import defaultdict
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from typing import Any
from uuid import uuid4

from apgar.api.metrics import (
    ASSEMBLY_ERRORS,
    ASSEMBLY_LAG,
    TURNS_ASSEMBLED,
    TURNS_DROPPED,
    TURNS_LATE,
    TURNS_PARTIAL,
)
from apgar.assembly.cost import turn_cost
from apgar.assembly.resolution import (
    resolve_agent_name,
    resolve_environment,
    resolve_prompt_version,
    resolve_release,
    resolve_session,
    resolve_surface,
)
from apgar.assembly.tools import (
    TurnKeyInfo,
    build_tool_calls,
    elapsed_ms,
    loop_flag,
    tool_retries,
)
from apgar.config import Settings
from apgar.domain.canonical import canonical_json
from apgar.domain.enums import OutputFormat, Source, SpanKind, SpanStatus
from apgar.domain.models import (
    Agent,
    IngestToken,
    SpanRow,
    ToolCallRow,
    TraceStateRow,
    TurnKey,
    TurnRow,
)
from apgar.domain.settings import ReleaseSettings, SurfaceMapping, VerdictSettings
from apgar.domain.time import to_iso
from apgar.normalize.normalizer import HmacKeys
from apgar.storage.interfaces import EventStore, MetaStore

_LOG = logging.getLogger("apgar.assembly")
_CLASS_KINDS = {SpanKind.invoke_workflow, SpanKind.invoke_agent}
_TOKEN_TTL_SECONDS = 60


@dataclass(slots=True)
class _Pin:
    root_span_id: str
    release: str
    start_ts: datetime
    agent_id: str
    version: int


@dataclass(slots=True)
class _AssemblyWrite:
    turns: tuple[TurnRow, ...]
    tools: tuple[ToolCallRow, ...]
    state: TraceStateRow


def _jsonable(value: Any) -> Any:
    if isinstance(value, datetime):
        return to_iso(value)
    if isinstance(value, SpanKind | SpanStatus | Source | OutputFormat):
        return value.value
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    return value


def _without(row: TurnRow | ToolCallRow, dropped: set[str]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for key, value in asdict(row).items():
        if key not in dropped:
            payload[key] = _jsonable(value)
    return payload


def _content_hash(turn: TurnRow, tools: Sequence[ToolCallRow]) -> str:
    payload = {
        "tools": [_without(row, {"version"}) for row in tools],
        "turn": _without(turn, {"version", "ingested_at"}),
    }
    return hashlib.sha256(canonical_json(payload)).hexdigest()


def _earliest(spans: Sequence[SpanRow]) -> SpanRow:
    return min(spans, key=lambda span: (span.start_ts, span.span_id))


def _has_class_ancestor(span: SpanRow, by_id: dict[str, SpanRow]) -> bool:
    seen: set[str] = set()
    parent_id = span.parent_span_id
    while parent_id and parent_id not in seen:
        seen.add(parent_id)
        parent = by_id.get(parent_id)
        if parent is None:
            return False
        if parent.kind in _CLASS_KINDS:
            return True
        parent_id = parent.parent_span_id
    return False


def _descendants(root: SpanRow, spans: Sequence[SpanRow]) -> list[SpanRow]:
    children: dict[str, list[SpanRow]] = defaultdict(list)
    for span in spans:
        if span.parent_span_id:
            children[span.parent_span_id].append(span)
    seen = {root.span_id}
    stack = [root.span_id]
    while stack:
        parent_id = stack.pop()
        for child in children.get(parent_id, []):
            if child.span_id in seen:
                continue
            seen.add(child.span_id)
            stack.append(child.span_id)
    return [span for span in spans if span.span_id in seen]


def _sum_optional(values: Sequence[int | None]) -> int | None:
    present = [value for value in values if value is not None]
    if not present:
        return None
    return sum(present)


def _unique_models(spans: Sequence[SpanRow]) -> list[str]:
    found: list[str] = []
    for span in spans:
        if span.response_model and span.response_model not in found:
            found.append(span.response_model)
    return found


def _root_from_turn_id(turn_id: str) -> str:
    if ":" not in turn_id:
        return turn_id
    return turn_id.split(":", 1)[1]


def _auto_agent(name: str, now: datetime) -> Agent:
    return Agent(
        id=str(uuid4()),
        name=name,
        source=Source.otlp,
        langfuse_connection_id="",
        filter=None,
        environment="",
        surface_mapping=SurfaceMapping(),
        release_settings=ReleaseSettings(),
        metric_settings={},
        verdict_settings=VerdictSettings(),
        output_format=OutputFormat.text,
        slack_connection_id="",
        is_demo=False,
        created_at=now,
        updated_at=now,
        deleted_at=None,
    )


class Assembler:
    def __init__(
        self,
        event_store: EventStore,
        meta_store: MetaStore,
        settings: Settings,
        keys: HmacKeys,
        clock: Callable[[], datetime],
        on_turn_assembled: Callable[[TurnRow, Agent, datetime], Awaitable[None]] | None = None,
    ) -> None:
        self._events = event_store
        self._meta = meta_store
        self._settings = settings
        self._keys = keys
        self._clock = clock
        self._on_turn_assembled = on_turn_assembled
        self._tokens: dict[str, tuple[IngestToken | None, datetime]] = {}
        self._cache_agents = False
        self._agent_by_id: dict[str, Agent | None] = {}
        self._agent_by_name: dict[str, Agent] = {}
        self._span_cache: dict[tuple[str, str], list[SpanRow]] | None = None
        self._turn_cache: dict[str, TurnKey | None] | None = None
        self._defer = False
        self._pending: list[_AssemblyWrite] = []
        self._pending_callbacks: list[tuple[TurnRow, Agent, datetime]] = []

    async def run_once(self, now: datetime, *, skip_source: str | None = None) -> int:
        due = await self._events.traces_due_for_assembly(
            now,
            self._settings.assembly_quiet_seconds,
            self._settings.assembly_max_age_seconds,
            limit=200,
        )
        if skip_source is not None:
            due = [state for state in due if state.source_id != skip_source]
        if not due:
            ASSEMBLY_LAG.set(0)
            return 0
        oldest = min(state.last_span_at for state in due)
        ASSEMBLY_LAG.set(max(0.0, (now - oldest).total_seconds()))
        self._cache_agents = True
        self._agent_by_id = {}
        self._agent_by_name = {}
        self._span_cache = await self._prefetch_spans(due)
        self._turn_cache = await self._prefetch_turns(due)
        self._defer = True
        self._pending = []
        self._pending_callbacks = []
        processed = 0
        callbacks: list[tuple[TurnRow, Agent, datetime]] = []
        try:
            for state in due:
                processed += 1
                try:
                    await self.assemble_trace(state, now)
                except Exception:
                    _LOG.exception(
                        "assembly failed",
                        extra={"trace_id": state.trace_id, "source_id": state.source_id},
                    )
                    ASSEMBLY_ERRORS.inc()
        finally:
            self._defer = False
            self._span_cache = None
            self._turn_cache = None
            self._cache_agents = False
            await self._flush_pending()
            callbacks = self._pending_callbacks
            self._pending_callbacks = []
        hook = self._on_turn_assembled
        if hook is not None:
            for turn, agent, assembled_at in callbacks:
                try:
                    await hook(turn, agent, assembled_at)
                except Exception:
                    _LOG.exception(
                        "turn assembled hook failed",
                        extra={"agent": agent.name, "release": turn.release},
                    )
        return processed

    async def _prefetch_spans(
        self, due: Sequence[TraceStateRow]
    ) -> dict[tuple[str, str], list[SpanRow]] | None:
        load = getattr(self._events, "spans_of_traces", None)
        if load is None:
            return None
        keys = [(state.source_id, state.trace_id) for state in due]
        loaded: dict[tuple[str, str], list[SpanRow]] = await load(keys)
        return loaded

    async def _prefetch_turns(
        self, due: Sequence[TraceStateRow]
    ) -> dict[str, TurnKey | None] | None:
        load = getattr(self._events, "find_turns_by_traces", None)
        if load is None:
            return None
        needed = [
            state.trace_id
            for state in due
            if not (state.root_span_id and state.start_ts is not None)
        ]
        if not needed:
            return {}
        loaded: dict[str, TurnKey | None] = await load(needed)
        return loaded

    async def _spans(self, source_id: str, trace_id: str) -> list[SpanRow]:
        if self._span_cache is not None:
            return list(self._span_cache.get((source_id, trace_id), []))
        return await self._events.spans_of_trace(source_id, trace_id)

    def _remember_agent(self, agent: Agent) -> None:
        if not self._cache_agents:
            return
        self._agent_by_id[agent.id] = agent
        self._agent_by_name[agent.name] = agent

    async def _agent(self, agent_id: str) -> Agent | None:
        if self._cache_agents and agent_id in self._agent_by_id:
            return self._agent_by_id[agent_id]
        agent = await self._meta.get_agent(agent_id)
        if self._cache_agents:
            self._agent_by_id[agent_id] = agent
            if agent is not None:
                self._agent_by_name[agent.name] = agent
        return agent

    async def _agent_named(self, name: str) -> Agent | None:
        if self._cache_agents and name in self._agent_by_name:
            return self._agent_by_name[name]
        agent = await self._meta.get_agent_by_name(name)
        if agent is not None:
            self._remember_agent(agent)
        return agent

    async def _save_state(self, state: TraceStateRow) -> None:
        write = _AssemblyWrite((), (), state)
        if self._defer:
            self._pending.append(write)
            return
        await self._write_many([write])

    async def _save_assembled(
        self,
        turn: TurnRow,
        tool_rows: Sequence[ToolCallRow],
        state: TraceStateRow,
    ) -> None:
        write = _AssemblyWrite((turn,), tuple(tool_rows), state)
        if self._defer:
            self._pending.append(write)
            return
        await self._write_many([write])

    async def _write_many(self, writes: Sequence[_AssemblyWrite]) -> None:
        turns = [turn for item in writes for turn in item.turns]
        tools = [row for item in writes for row in item.tools]
        states = [item.state for item in writes]
        if turns:
            await self._events.upsert_turns(turns)
        if tools:
            await self._events.insert_tool_calls(tools)
        if states:
            await self._events.upsert_trace_state(states)

    async def _flush_pending(self) -> None:
        pending = self._pending
        self._pending = []
        if not pending:
            return
        try:
            await self._write_many(pending)
        except Exception:
            _LOG.exception("assembly batch insert failed; retrying per trace")
            for item in pending:
                try:
                    await self._write_many([item])
                except Exception:
                    _LOG.exception(
                        "assembly insert failed",
                        extra={"trace_id": item.state.trace_id, "source_id": item.state.source_id},
                    )
                    ASSEMBLY_ERRORS.inc()

    async def assemble_trace(self, state: TraceStateRow, now: datetime) -> None:
        spans = await self._spans(state.source_id, state.trace_id)
        if not spans:
            await self._save_state(replace(state, assembled_at=now, updated_at=now))
            return
        by_id = {span.span_id: span for span in spans}
        has_null_parent = any(span.parent_span_id == "" for span in spans)
        partial = not has_null_parent
        class_roots = [
            span
            for span in spans
            if span.kind in _CLASS_KINDS and not _has_class_ancestor(span, by_id)
        ]
        if class_roots:
            root = _earliest(class_roots)
        elif has_null_parent:
            root = _earliest([span for span in spans if span.parent_span_id == ""])
        else:
            topmost = [span for span in spans if span.parent_span_id not in by_id]
            root = _earliest(topmost or spans)
        descendants = _descendants(root, spans)
        pin = await self._pin(state)
        if pin is not None:
            agent = await self._agent(pin.agent_id)
            if agent is None:
                await self._drop(state, now, "agent_not_found")
                return
        else:
            agent = await self._resolve_agent(state, root, spans, now)
            if agent is None:
                return
        chat_spans = sorted(
            (span for span in descendants if span.kind == SpanKind.chat),
            key=lambda span: (span.start_ts, span.span_id),
        )
        first_chat = chat_spans[0].attributes if chat_spans else None
        release = resolve_release(root.attributes, agent.release_settings)
        environment = resolve_environment(root.attributes)
        session_id, inferred = resolve_session(root.attributes, state.trace_id)
        prompt_version = resolve_prompt_version(root.attributes, first_chat)
        surface = resolve_surface(root.attributes, agent.surface_mapping)
        if pin is None:
            turn_id = f"{state.trace_id}:{root.span_id}"
            start_ts = root.start_ts
            root_span_id = root.span_id
            version = 1
            agent_id = agent.id
        else:
            turn_id = f"{state.trace_id}:{pin.root_span_id}"
            release = pin.release
            start_ts = pin.start_ts
            root_span_id = pin.root_span_id
            version = pin.version + 1
            agent_id = pin.agent_id
        tool_spans = [span for span in descendants if span.kind == SpanKind.execute_tool]
        tool_rows = build_tool_calls(
            tool_spans,
            TurnKeyInfo(
                agent_id=agent_id,
                release=release,
                turn_start_ts=start_ts,
                turn_id=turn_id,
                session_id=session_id,
                surface=surface,
                version=version,
            ),
        )
        output_chars = root.output_chars
        output_valid = root.output_json_valid
        if output_chars is None and chat_spans:
            output_chars = chat_spans[-1].output_chars
        if output_valid is None and chat_spans:
            output_valid = chat_spans[-1].output_json_valid
        format_ok = output_valid if agent.output_format == OutputFormat.json else None
        latency_ms = elapsed_ms(root.start_ts, root.end_ts)
        end_ts = max(span.end_ts for span in descendants)
        raw_source = root.attributes.get("apgar.source", "otlp")
        try:
            source = Source(raw_source)
        except ValueError:
            source = Source.otlp
        turn = TurnRow(
            agent_id=agent_id,
            release=release,
            start_ts=start_ts,
            turn_id=turn_id,
            trace_id=state.trace_id,
            root_span_id=root_span_id,
            source_id=state.source_id,
            environment=environment,
            prompt_version=prompt_version,
            session_id=session_id,
            session_inferred=inferred,
            surface=surface,
            end_ts=end_ts,
            latency_ms=latency_ms,
            llm_calls=len(chat_spans),
            llm_errors=sum(1 for span in chat_spans if span.status == SpanStatus.error),
            tool_calls=len(tool_rows),
            tool_errors=sum(1 for row in tool_rows if row.status == SpanStatus.error),
            tool_retries=tool_retries(tool_rows),
            loop_flag=loop_flag(tool_rows),
            zero_tool_flag=len(tool_rows) == 0,
            input_tokens=_sum_optional([span.input_tokens for span in chat_spans]),
            output_tokens=_sum_optional([span.output_tokens for span in chat_spans]),
            output_chars=output_chars,
            cost_usd=turn_cost(chat_spans),
            primary_response_model=chat_spans[-1].response_model if chat_spans else "",
            response_models=_unique_models(chat_spans),
            format_ok=format_ok,
            late=root.late,
            partial=partial,
            source=source,
            ingested_at=now,
            version=version,
        )
        digest = _content_hash(turn, tool_rows)
        if digest == state.content_hash and state.root_span_id != "":
            await self._save_state(replace(state, assembled_at=now, updated_at=now))
            return
        await self._save_assembled(
            turn,
            tool_rows,
            replace(
                state,
                agent_id=agent_id,
                root_span_id=root_span_id,
                release=release,
                start_ts=start_ts,
                assembled_at=now,
                assembled_version=version,
                content_hash=digest,
                updated_at=now,
            ),
        )
        TURNS_ASSEMBLED.labels(agent=agent.name).inc()
        if partial:
            TURNS_PARTIAL.labels(agent=agent.name).inc()
        if turn.late:
            TURNS_LATE.labels(agent=agent.name).inc()
        if self._on_turn_assembled is None:
            return
        if self._defer:
            self._pending_callbacks.append((turn, agent, now))
            return
        await self._on_turn_assembled(turn, agent, now)

    async def _pin(self, state: TraceStateRow) -> _Pin | None:
        if state.root_span_id and state.start_ts is not None:
            return _Pin(
                root_span_id=state.root_span_id,
                release=state.release,
                start_ts=state.start_ts,
                agent_id=state.agent_id,
                version=state.assembled_version,
            )
        found: TurnKey | None
        if self._turn_cache is not None:
            found = self._turn_cache.get(state.trace_id)
        else:
            found = await self._events.find_turn_by_trace(state.trace_id)
        if found is None:
            return None
        return _Pin(
            root_span_id=_root_from_turn_id(found.turn_id),
            release=found.release,
            start_ts=found.start_ts,
            agent_id=found.agent_id,
            version=found.version,
        )

    async def _resolve_agent(
        self,
        state: TraceStateRow,
        root: SpanRow,
        spans: Sequence[SpanRow],
        now: datetime,
    ) -> Agent | None:
        hint = root.agent_hint or next((span.agent_hint for span in spans if span.agent_hint), "")
        if hint:
            agent = await self._agent(hint)
            if agent is None:
                await self._drop(state, now, "agent_not_found")
                return None
            return agent
        name = resolve_agent_name(root.attributes)
        if name is None:
            await self._drop(state, now, "no_agent")
            return None
        agent = await self._agent_named(name)
        if agent is not None:
            return agent
        token = await self._token(state.source_id, now)
        agent = await self._agent_named(name)
        if agent is not None:
            return agent
        if token is not None and not token.auto_create_agents:
            await self._drop(state, now, "agent_not_found")
            return None
        created = _auto_agent(name, now)
        await self._meta.upsert_agent(created)
        self._remember_agent(created)
        return created

    async def _token(self, source_id: str, now: datetime) -> IngestToken | None:
        cached = self._tokens.get(source_id)
        if cached is not None and (now - cached[1]).total_seconds() < _TOKEN_TTL_SECONDS:
            return cached[0]
        tokens = await self._meta.list_ingest_tokens()
        found = next((token for token in tokens if token.id == source_id), None)
        self._tokens[source_id] = (found, now)
        return found

    async def _drop(self, state: TraceStateRow, now: datetime, reason: str) -> None:
        TURNS_DROPPED.labels(reason=reason).inc()
        _LOG.info(
            "turn dropped",
            extra={"trace_id": state.trace_id, "source_id": state.source_id, "reason": reason},
        )
        await self._save_state(replace(state, assembled_at=now, agent_id="", updated_at=now))
