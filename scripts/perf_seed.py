"""Seed a non-demo agent with synthetic turns for the latency check."""

from __future__ import annotations

import argparse
import asyncio
import math
import random
import time
from datetime import datetime, timedelta

from repo_env import load_repo_env

from apgar.config import load_settings
from apgar.domain.enums import OutputFormat, ReasonCode, Source, SpanStatus
from apgar.domain.models import Agent, ToolCallRow, TurnRow
from apgar.domain.settings import ReleaseSettings, SurfaceMapping, VerdictSettings
from apgar.domain.time import utcnow
from apgar.security import SecretBox
from apgar.storage.clickhouse.client import create_client
from apgar.storage.clickhouse.event_store import ClickHouseEventStore
from apgar.storage.clickhouse.meta_store import ClickHouseMetaStore
from apgar.worker.jobs.release_discovery import new_release

_SURFACES = (("slack", 0.50), ("web", 0.35), ("telegram", 0.15))
_MODELS = ("gpt-4.1", "gpt-4.1-mini")
_TOOLS = (("sql_query", 0.75), ("get_invoice", 0.15), ("send_email", 0.10))
_BATCH = 20_000


def _hour_weight(hour: int) -> float:
    if 6 <= hour < 20:
        return 0.4 + 0.6 * math.sin(math.pi * (hour - 6) / 14.0)
    return 0.4


def _pick(rng: random.Random, pairs: tuple[tuple[str, float], ...]) -> str:
    draw = rng.random()
    cursor = 0.0
    for name, weight in pairs:
        cursor += weight
        if draw <= cursor:
            return name
    return pairs[-1][0]


def _stamp(rng: random.Random, origin: datetime, days: int) -> datetime:
    weights = [_hour_weight(hour) for hour in range(24)]
    hour = rng.choices(range(24), weights=weights, k=1)[0]
    day = rng.randrange(days)
    return origin + timedelta(
        days=day,
        hours=hour,
        minutes=rng.randrange(60),
        seconds=rng.randrange(60),
    )


def _turn(
    agent_id: str,
    release: str,
    index: int,
    start_ts: datetime,
    surface: str,
    model: str,
    tool_calls: int,
    error: bool,
) -> TurnRow:
    return TurnRow(
        agent_id=agent_id,
        release=release,
        start_ts=start_ts,
        turn_id=f"{release}-{index:07d}",
        trace_id=f"{index:032x}",
        root_span_id="cd" * 8,
        source_id="perf",
        environment="production",
        prompt_version="v1",
        session_id=f"{release}-s{index % 40000}",
        session_inferred=False,
        surface=surface,
        end_ts=start_ts + timedelta(milliseconds=800),
        latency_ms=400 + (index % 2000),
        llm_calls=1,
        llm_errors=0,
        tool_calls=tool_calls,
        tool_errors=1 if error else 0,
        tool_retries=1 if error else 0,
        loop_flag=False,
        zero_tool_flag=tool_calls == 0,
        input_tokens=40,
        output_tokens=120 + (index % 80),
        output_chars=80,
        cost_usd=0.002,
        primary_response_model=model,
        response_models=[model],
        format_ok=True,
        late=False,
        partial=False,
        source=Source.otlp,
        ingested_at=start_ts,
        version=1,
    )


def _calls(
    agent_id: str,
    release: str,
    index: int,
    start_ts: datetime,
    surface: str,
    count: int,
    error: bool,
    rng: random.Random,
) -> list[ToolCallRow]:
    rows: list[ToolCallRow] = []
    for offset in range(count):
        rows.append(
            ToolCallRow(
                agent_id=agent_id,
                release=release,
                turn_start_ts=start_ts,
                turn_id=f"{release}-{index:07d}",
                tool_call_id=f"{release}-{index:07d}-{offset}",
                session_id=f"{release}-s{index % 40000}",
                tool_name=_pick(rng, _TOOLS),
                call_start_ts=start_ts,
                duration_ms=20,
                status=SpanStatus.error if error and offset == 0 else SpanStatus.ok,
                error_type="tool_error" if error and offset == 0 else "",
                args_hash="",
                is_retry=False,
                surface=surface,
                version=1,
            )
        )
    return rows


async def _flush_calls(event_store: ClickHouseEventStore, rows: list[ToolCallRow]) -> None:
    for offset in range(0, len(rows), _BATCH):
        await event_store.insert_tool_calls(rows[offset : offset + _BATCH])


async def seed(turns: int, tool_calls: int, agent_name: str, days: int) -> None:
    load_repo_env()
    settings = load_settings()
    client = await create_client(settings)
    started = time.perf_counter()
    try:
        event_store = ClickHouseEventStore(client)
        meta_store = ClickHouseMetaStore(
            client, SecretBox(settings.secret_key, settings.secret_key_previous)
        )
        now = utcnow()
        origin = (now - timedelta(days=days)).replace(minute=0, second=0, microsecond=0)
        agent = Agent(
            id="00000000-0000-4000-8000-00000000a001",
            name=agent_name,
            source=Source.otlp,
            langfuse_connection_id="",
            filter=None,
            environment="production",
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
        await meta_store.upsert_agent(agent)
        release_count = 5
        base, extra_turns = divmod(turns, release_count)
        sizes = [base + (1 if index < extra_turns else 0) for index in range(release_count)]
        tool_base, extra_tools = divmod(tool_calls, max(turns, 1))
        rng = random.Random(42)
        cursor = 0
        names: list[str] = []
        for release_index, size in enumerate(sizes):
            release = f"perf-{release_index + 1}"
            names.append(release)
            first: datetime | None = None
            batch: list[TurnRow] = []
            calls: list[ToolCallRow] = []
            for local in range(size):
                index = cursor + local
                start_ts = _stamp(rng, origin, days)
                if first is None or start_ts < first:
                    first = start_ts
                count = tool_base + (1 if index < extra_tools else 0)
                error = rng.random() < 0.02
                surface = _pick(rng, _SURFACES)
                model = _MODELS[index % len(_MODELS)]
                batch.append(
                    _turn(agent.id, release, index, start_ts, surface, model, count, error)
                )
                calls.extend(_calls(agent.id, release, index, start_ts, surface, count, error, rng))
                if len(batch) >= _BATCH:
                    await event_store.upsert_turns(batch)
                    await _flush_calls(event_store, calls)
                    batch = []
                    calls = []
            if batch:
                await event_store.upsert_turns(batch)
                await _flush_calls(event_store, calls)
            seen = first if first is not None else origin
            await meta_store.upsert_release(
                new_release(agent.id, release, seen, ReasonCode.no_baseline, now)
            )
            cursor += size
            print(f"seeded {release} turns={size}", flush=True)
        elapsed = time.perf_counter() - started
        print(
            f"perf seed ok agent={agent_name} releases={','.join(names)} "
            f"turns={turns} tool_calls={tool_calls} elapsed_s={elapsed:.1f}"
        )
    finally:
        await client.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed synthetic turns for performance checks.")
    parser.add_argument("--turns", type=int, default=1_000_000)
    parser.add_argument("--tool-calls", type=int, default=5_000_000)
    parser.add_argument("--agent", default="perf-agent")
    parser.add_argument("--days", type=int, default=30)
    args = parser.parse_args()
    asyncio.run(seed(args.turns, args.tool_calls, args.agent, args.days))


if __name__ == "__main__":
    main()
