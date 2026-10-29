from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta

from apgar.assembly.assembler import Assembler
from apgar.config import Settings
from apgar.domain.enums import OutputFormat, Source, SpanKind
from apgar.domain.models import TraceStateRow, TurnRow
from apgar.domain.settings import ReleaseSettings, SurfaceMapping
from apgar.ingest.pipeline import write_batch
from apgar.normalize.normalizer import normalize
from apgar.normalize.otlp import decode_request, iter_raw_spans
from apgar.storage.memory import InMemoryEventStore, InMemoryMetaStore
from tests.factories import make_agent, make_ingest_token
from tests.support import FIXTURE_NOW, MemStores, keys_for, load_fixture


def _assembler(
    event: InMemoryEventStore,
    meta: InMemoryMetaStore,
    settings: Settings,
) -> Assembler:
    return Assembler(event, meta, settings, keys_for(settings), lambda: FIXTURE_NOW)


async def _ingest(
    name: str,
    event: InMemoryEventStore,
    settings: Settings,
    now: datetime,
    *,
    agent_hint: str = "",
    source_id: str = "src",
) -> None:
    rows = [
        normalize(
            raw,
            source_id=source_id,
            source=Source.otlp,
            agent_hint=agent_hint,
            now=now,
            late_days=settings.late_span_days,
            keys=keys_for(settings),
        )
        for raw in iter_raw_spans(decode_request(load_fixture(name), "application/json", None))
        if raw.trace_id
    ]
    await write_batch(event, rows, now)


def _turns(event: InMemoryEventStore) -> list[TurnRow]:
    return list(event._turns.values())


async def test_genai_basic(settings: Settings, mem_stores: MemStores) -> None:
    event, meta = mem_stores
    await _ingest("genai_basic.json", event, settings, FIXTURE_NOW)
    count = await _assembler(event, meta, settings).run_once(FIXTURE_NOW + timedelta(seconds=61))
    assert count == 1
    turn = _turns(event)[0]
    assert turn.release == "a1b2c3d"
    assert turn.environment == "production"
    assert turn.session_id == "s-1"
    assert turn.session_inferred is False
    assert turn.llm_calls == 1
    assert turn.tool_calls == 1
    assert turn.zero_tool_flag is False
    assert turn.output_chars and turn.output_chars > 0
    assert turn.loop_flag is False
    assert turn.tool_retries == 0
    assert turn.cost_usd == 0.003
    assert turn.primary_response_model == "gpt-4.1"
    assert turn.partial is False


async def test_retry_loop(settings: Settings, mem_stores: MemStores) -> None:
    event, meta = mem_stores
    await _ingest("genai_retry_loop.json", event, settings, FIXTURE_NOW)
    await _assembler(event, meta, settings).run_once(FIXTURE_NOW + timedelta(seconds=61))
    turn = _turns(event)[0]
    tools = list(event._tools.values())
    tools.sort(key=lambda row: row.call_start_ts)
    assert tools[1].is_retry is True
    assert turn.tool_retries == 1
    assert turn.loop_flag is True
    assert turn.tool_errors == 1


async def test_no_args(settings: Settings, mem_stores: MemStores) -> None:
    event, meta = mem_stores
    await _ingest("genai_no_args.json", event, settings, FIXTURE_NOW)
    await _assembler(event, meta, settings).run_once(FIXTURE_NOW + timedelta(seconds=61))
    turn = _turns(event)[0]
    assert all(row.args_hash == "" for row in event._tools.values())
    assert all(row.is_retry is None for row in event._tools.values())
    assert turn.loop_flag is None
    assert turn.tool_retries is None


async def test_tokens_without_cost_leave_cost_unset(
    settings: Settings, mem_stores: MemStores
) -> None:
    event, meta = mem_stores
    await _ingest("genai_no_cost.json", event, settings, FIXTURE_NOW)
    await _assembler(event, meta, settings).run_once(FIXTURE_NOW + timedelta(seconds=61))
    turn = _turns(event)[0]
    assert turn.input_tokens == 900
    assert turn.cost_usd is None


async def test_openinference_basic(settings: Settings, mem_stores: MemStores) -> None:
    event, meta = mem_stores
    await _ingest("openinference_basic.json", event, settings, FIXTURE_NOW)
    await _assembler(event, meta, settings).run_once(FIXTURE_NOW + timedelta(seconds=61))
    turn = _turns(event)[0]
    assert turn.release == "untagged"
    assert turn.session_inferred is False
    assert turn.tool_calls == 1
    assert next(iter(event._tools.values())).args_hash != ""


async def test_langfuse_otel_basic(settings: Settings, mem_stores: MemStores) -> None:
    event, meta = mem_stores
    await _ingest("langfuse_otel_basic.json", event, settings, FIXTURE_NOW)
    await _assembler(event, meta, settings).run_once(FIXTURE_NOW + timedelta(seconds=61))
    turn = _turns(event)[0]
    assert turn.prompt_version == "billing@7"
    assert turn.input_tokens == 900
    assert turn.output_tokens == 150
    assert turn.cost_usd == 0.003
    root = (await event.spans_of_trace("src", "7" * 32))[0]
    assert root.kind is SpanKind.invoke_agent


async def test_nested_subagent(settings: Settings, mem_stores: MemStores) -> None:
    event, meta = mem_stores
    await _ingest("nested_subagent.json", event, settings, FIXTURE_NOW)
    await _assembler(event, meta, settings).run_once(FIXTURE_NOW + timedelta(seconds=61))
    turns = _turns(event)
    assert len(turns) == 1
    assert turns[0].llm_calls == 2
    assert turns[0].root_span_id == "7878787878787878"


async def test_run_once_assembles_up_to_the_limit(
    settings: Settings, mem_stores: MemStores
) -> None:
    event, meta = mem_stores
    await _ingest("genai_basic.json", event, settings, FIXTURE_NOW, source_id="a")
    await _ingest("genai_basic.json", event, settings, FIXTURE_NOW, source_id="b")
    assembler = _assembler(event, meta, settings)
    later = FIXTURE_NOW + timedelta(seconds=61)
    assert await assembler.run_once(later, limit=1) == 1
    assert await assembler.run_once(later, limit=1) == 1
    assert await assembler.run_once(later, limit=1) == 0


async def test_two_top_agents(settings: Settings, mem_stores: MemStores) -> None:
    event, meta = mem_stores
    await _ingest("two_top_agents.json", event, settings, FIXTURE_NOW)
    await _assembler(event, meta, settings).run_once(FIXTURE_NOW + timedelta(seconds=61))
    turns = _turns(event)
    assert len(turns) == 1
    assert turns[0].llm_calls == 1
    assert turns[0].release == "early"
    assert turns[0].root_span_id == "8989898989898989"


async def test_partial_no_root(settings: Settings, mem_stores: MemStores) -> None:
    event, meta = mem_stores
    await _ingest("partial_no_root.json", event, settings, FIXTURE_NOW)
    assembler = _assembler(event, meta, settings)
    assert await assembler.run_once(FIXTURE_NOW + timedelta(seconds=61)) == 0
    assert _turns(event) == []
    assert await assembler.run_once(FIXTURE_NOW + timedelta(seconds=601)) == 1
    turn = _turns(event)[0]
    assert turn.partial is True
    assert turn.root_span_id == "9292929292929292"
    assert turn.llm_calls == 1


async def test_untagged_and_staging(settings: Settings, mem_stores: MemStores) -> None:
    event, meta = mem_stores
    await _ingest("untagged.json", event, settings, FIXTURE_NOW)
    await _ingest("env_staging.json", event, settings, FIXTURE_NOW)
    await _assembler(event, meta, settings).run_once(FIXTURE_NOW + timedelta(seconds=61))
    by_trace = {turn.trace_id: turn for turn in _turns(event)}
    assert by_trace["b" * 32].release == "untagged"
    assert by_trace["c" * 32].environment == "staging"


async def test_late_span(settings: Settings, mem_stores: MemStores) -> None:
    event, meta = mem_stores
    await _ingest("late_span.json", event, settings, FIXTURE_NOW)
    await _assembler(event, meta, settings).run_once(FIXTURE_NOW + timedelta(seconds=61))
    assert _turns(event)[0].late is True


async def test_content_absent(settings: Settings, mem_stores: MemStores) -> None:
    event, meta = mem_stores
    await _ingest("content_absent.json", event, settings, FIXTURE_NOW)
    await _assembler(event, meta, settings).run_once(FIXTURE_NOW + timedelta(seconds=61))
    turn = _turns(event)[0]
    assert turn.output_chars is None
    assert turn.format_ok is None


async def test_json_output_format_ok(settings: Settings, mem_stores: MemStores) -> None:
    event, meta = mem_stores
    await meta.upsert_agent(
        make_agent(
            FIXTURE_NOW,
            name="support-agent",
            output_format=OutputFormat.json,
            release_settings=ReleaseSettings(),
            surface_mapping=SurfaceMapping(),
        )
    )
    await _ingest("json_output.json", event, settings, FIXTURE_NOW)
    await _assembler(event, meta, settings).run_once(FIXTURE_NOW + timedelta(seconds=61))
    turn = _turns(event)[0]
    assert turn.format_ok is True
    text_event, text_meta = InMemoryEventStore(), InMemoryMetaStore()
    await _ingest("json_output.json", text_event, settings, FIXTURE_NOW)
    await _assembler(text_event, text_meta, settings).run_once(FIXTURE_NOW + timedelta(seconds=61))
    assert _turns(text_event)[0].format_ok is None


async def test_reassembly_keeps_key(settings: Settings, mem_stores: MemStores) -> None:
    event, meta = mem_stores
    await _ingest("reassembly_part1.json", event, settings, FIXTURE_NOW)
    assembler = _assembler(event, meta, settings)
    await assembler.run_once(FIXTURE_NOW + timedelta(seconds=61))
    first = _turns(event)[0]
    await _ingest("reassembly_part2.json", event, settings, FIXTURE_NOW + timedelta(minutes=2))
    await assembler.run_once(FIXTURE_NOW + timedelta(minutes=3, seconds=1))
    turns = _turns(event)
    assert len(turns) == 1
    assert turns[0].turn_id == first.turn_id
    assert turns[0].start_ts == first.start_ts
    assert turns[0].release == first.release
    assert turns[0].version == 2
    assert turns[0].tool_calls == 2
    assert len(event._tools) == 2


async def test_surface_mapping(settings: Settings, mem_stores: MemStores) -> None:
    event, meta = mem_stores
    await meta.upsert_agent(
        make_agent(
            FIXTURE_NOW,
            release_settings=ReleaseSettings(),
            surface_mapping=SurfaceMapping(from_attribute="metadata.channel"),
        )
    )
    await _ingest("surface_mapping.json", event, settings, FIXTURE_NOW)
    await _assembler(event, meta, settings).run_once(FIXTURE_NOW + timedelta(seconds=61))
    assert _turns(event)[0].surface == "slack"


async def test_due_rules_quiet_and_deadline(settings: Settings, mem_stores: MemStores) -> None:
    event, _meta = mem_stores
    quiet = TraceStateRow(
        source_id="src",
        trace_id="q" * 32,
        first_span_at=FIXTURE_NOW,
        last_span_at=FIXTURE_NOW,
        span_count=1,
        has_root=True,
        agent_id="",
        root_span_id="",
        release="",
        start_ts=None,
        assembled_at=None,
        assembled_version=0,
        content_hash="",
        updated_at=FIXTURE_NOW,
    )
    aged = TraceStateRow(
        source_id="src",
        trace_id="d" * 32,
        first_span_at=FIXTURE_NOW,
        last_span_at=FIXTURE_NOW,
        span_count=1,
        has_root=False,
        agent_id="",
        root_span_id="",
        release="",
        start_ts=None,
        assembled_at=None,
        assembled_version=0,
        content_hash="",
        updated_at=FIXTURE_NOW,
    )
    await event.upsert_trace_state([quiet, aged])
    early = FIXTURE_NOW + timedelta(seconds=59)
    assert await event.traces_due_for_assembly(early, 60, 600, 10) == []
    later = FIXTURE_NOW + timedelta(seconds=61)
    due = await event.traces_due_for_assembly(later, 60, 600, 10)
    assert [row.trace_id for row in due] == ["q" * 32]
    deadline = FIXTURE_NOW + timedelta(seconds=600)
    both = await event.traces_due_for_assembly(deadline, 60, 600, 10)
    assert {row.trace_id for row in both} == {"q" * 32, "d" * 32}
    assert settings


async def test_agent_auto_create_and_slugify(settings: Settings, mem_stores: MemStores) -> None:
    event, meta = mem_stores
    await _ingest("untagged.json", event, settings, FIXTURE_NOW)
    spans = await event.spans_of_trace("src", "b" * 32)
    spans[0].attributes["gen_ai.agent.name"] = "Billing Copilot"
    await event.insert_spans(spans)
    await _assembler(event, meta, settings).run_once(FIXTURE_NOW + timedelta(seconds=61))
    agents = await meta.list_agents()
    assert [agent.name for agent in agents] == ["billing-copilot"]
    assert _turns(event)[0].agent_id == agents[0].id


async def test_agent_not_found_dropped_when_auto_create_false(
    settings: Settings, mem_stores: MemStores
) -> None:
    event, meta = mem_stores
    await meta.upsert_ingest_token(
        make_ingest_token(FIXTURE_NOW, id="src", auto_create_agents=False)
    )
    await _ingest("untagged.json", event, settings, FIXTURE_NOW, source_id="src")
    await _assembler(event, meta, settings).run_once(FIXTURE_NOW + timedelta(seconds=61))
    assert _turns(event) == []
    state = (await event.read_trace_state([("src", "b" * 32)]))[("src", "b" * 32)]
    assert state.assembled_at is not None
    assert state.agent_id == ""


async def test_pinned_facts_from_trace_state(settings: Settings, mem_stores: MemStores) -> None:
    event, meta = mem_stores
    await _ingest("genai_basic.json", event, settings, FIXTURE_NOW)
    assembler = _assembler(event, meta, settings)
    await assembler.run_once(FIXTURE_NOW + timedelta(seconds=61))
    first = _turns(event)[0]
    spans = await event.spans_of_trace("src", "1" * 32)
    root = next(span for span in spans if span.parent_span_id == "")
    root.attributes["gen_ai.agent.version"] = "changed"
    root.ingested_at = FIXTURE_NOW + timedelta(minutes=2)
    extra = root.__class__(**{field: getattr(root, field) for field in root.__dataclass_fields__})
    extra.span_id = "dddddddddddddddd"
    extra.parent_span_id = root.span_id
    extra.kind = SpanKind.execute_tool
    extra.tool_name = "sql_query"
    extra.args_hash = "abc"
    extra.name = "sql_query"
    extra.start_ts = root.start_ts + timedelta(seconds=1)
    extra.end_ts = extra.start_ts
    await event.insert_spans([root, extra])
    state = (await event.read_trace_state([("src", "1" * 32)]))[("src", "1" * 32)]
    await event.upsert_trace_state(
        [
            TraceStateRow(
                source_id=state.source_id,
                trace_id=state.trace_id,
                first_span_at=state.first_span_at,
                last_span_at=FIXTURE_NOW + timedelta(minutes=3),
                span_count=state.span_count,
                has_root=state.has_root,
                agent_id=state.agent_id,
                root_span_id=state.root_span_id,
                release=state.release,
                start_ts=state.start_ts,
                assembled_at=state.assembled_at,
                assembled_version=state.assembled_version,
                content_hash=state.content_hash,
                updated_at=FIXTURE_NOW + timedelta(minutes=3),
            )
        ]
    )
    await assembler.run_once(FIXTURE_NOW + timedelta(minutes=5))
    again = next(turn for turn in _turns(event) if turn.trace_id == "1" * 32)
    assert again.turn_id == first.turn_id
    assert again.start_ts == first.start_ts
    assert again.release == "a1b2c3d"
    assert again.version == 2


async def test_pinned_facts_from_turns_when_state_missing(
    settings: Settings, mem_stores: MemStores
) -> None:
    event, meta = mem_stores
    await _ingest("genai_basic.json", event, settings, FIXTURE_NOW)
    assembler = _assembler(event, meta, settings)
    await assembler.run_once(FIXTURE_NOW + timedelta(seconds=61))
    first = _turns(event)[0]
    state = (await event.read_trace_state([("src", "1" * 32)]))[("src", "1" * 32)]
    cleared = TraceStateRow(
        source_id=state.source_id,
        trace_id=state.trace_id,
        first_span_at=state.first_span_at,
        last_span_at=FIXTURE_NOW + timedelta(minutes=2),
        span_count=state.span_count,
        has_root=True,
        agent_id="",
        root_span_id="",
        release="",
        start_ts=None,
        assembled_at=None,
        assembled_version=0,
        content_hash="",
        updated_at=FIXTURE_NOW + timedelta(minutes=2),
    )
    await event.upsert_trace_state([cleared])
    await assembler.assemble_trace(cleared, FIXTURE_NOW + timedelta(minutes=4))
    again = next(turn for turn in _turns(event) if turn.trace_id == "1" * 32)
    assert again.turn_id == first.turn_id
    assert again.start_ts == first.start_ts
    assert again.release == first.release
    assert again.version == 2


async def test_identical_redelivery_writes_no_new_version(
    settings: Settings, mem_stores: MemStores
) -> None:
    event, meta = mem_stores
    await _ingest("genai_basic.json", event, settings, FIXTURE_NOW)
    assembler = _assembler(event, meta, settings)
    await assembler.run_once(FIXTURE_NOW + timedelta(seconds=61))
    await _ingest("genai_basic.json", event, settings, FIXTURE_NOW + timedelta(minutes=2))
    await assembler.run_once(FIXTURE_NOW + timedelta(minutes=4))
    turns = _turns(event)
    assert len(turns) == 1
    assert turns[0].version == 1
    state = (await event.read_trace_state([("src", "1" * 32)]))[("src", "1" * 32)]
    assert state.assembled_version == 1


async def test_token_binding_wins(settings: Settings, mem_stores: MemStores) -> None:
    event, meta = mem_stores
    bound = make_agent(
        FIXTURE_NOW, id="agent-a", name="bound-agent", release_settings=ReleaseSettings()
    )
    other = make_agent(
        FIXTURE_NOW,
        id="agent-b",
        name="billing-copilot",
        release_settings=ReleaseSettings(),
    )
    await meta.upsert_agent(bound)
    await meta.upsert_agent(other)
    await _ingest("genai_basic.json", event, settings, FIXTURE_NOW, agent_hint="agent-a")
    await _assembler(event, meta, settings).run_once(FIXTURE_NOW + timedelta(seconds=61))
    assert _turns(event)[0].agent_id == "agent-a"


async def test_batch_insert_failure_keeps_other_traces(settings: Settings) -> None:
    class Selective(InMemoryEventStore):
        async def upsert_turns(self, rows: Sequence[TurnRow]) -> None:
            if len(rows) > 1:
                raise RuntimeError("batch")
            if rows and rows[0].trace_id.startswith("bbbb"):
                raise RuntimeError("poison")
            await super().upsert_turns(rows)

    event = Selective()
    meta = InMemoryMetaStore()
    await _ingest("genai_basic.json", event, settings, FIXTURE_NOW)
    await _ingest("untagged.json", event, settings, FIXTURE_NOW)
    await _assembler(event, meta, settings).run_once(FIXTURE_NOW + timedelta(seconds=61))
    turns = _turns(event)
    assert [turn.trace_id for turn in turns] == ["1" * 32]
    poisoned = next(row for row in event._trace_state.values() if row.trace_id.startswith("bbbb"))
    assert poisoned.assembled_at is None
