from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

from apgar.assembly.assembler import Assembler
from apgar.config import Settings
from apgar.demo.scenarios import BILLING, SUPPORT, generate
from apgar.domain.enums import MetricId, MetricRole, OutputFormat, ReasonCode, Source
from apgar.domain.models import Agent, SpanRow
from apgar.domain.settings import DEFAULT_METRICS, ReleaseSettings, SurfaceMapping, VerdictSettings
from apgar.domain.time import monotonic_updated_at, to_iso, utcnow
from apgar.ingest.pipeline import write_batch
from apgar.normalize.normalizer import HmacKeys, normalize
from apgar.normalize.otlp import iter_raw_spans
from apgar.normalize.otlp_json import parse
from apgar.storage.interfaces import EventStore, MetaStore
from apgar.storage.types import ArmQuery, ReleaseActivity, ReleaseFilters
from apgar.worker.jobs.rollup import RollupJob

_SEEDED_AT = "demo.seeded_at"
_BATCH = 2000
# Larger assembly batches than the worker's let the seeded releases appear sooner.
_ASSEMBLY_BATCH = 2000
# The scripted FAIL and PASS outcomes were checked at this instant. Seeding at
# another time of day shifts the diurnal sample and the bootstrap seed.
DEMO_CLOCK = datetime(2026, 10, 8, 9, 30, tzinfo=UTC)


class DemoSeedError(Exception):
    pass


_DEMO_GUARDRAILS = {
    BILLING: frozenset({MetricId.tool_error_rate}),
    SUPPORT: frozenset(
        {
            MetricId.tool_error_rate,
            MetricId.tool_retry_rate,
            MetricId.loop_rate,
        }
    ),
}


def _demo_metrics(name: str) -> dict[str, dict[str, Any]]:
    # With the seeded volume, Bonferroni intervals on the other guardrails stay
    # wider than their tolerances, so a clean release could not reach PASS. The
    # support agent keeps the Behavior metrics its injected releases move.
    overrides: dict[str, dict[str, Any]] = {}
    for metric_id, settings in DEFAULT_METRICS.items():
        if settings.role is MetricRole.guardrail and metric_id not in _DEMO_GUARDRAILS[name]:
            overrides[metric_id.value] = {"role": "informational"}
    return overrides


def _demo_agent(name: str, now: datetime) -> Agent:
    billing = name == BILLING
    # Fixed ids keep bootstrap seeds stable across seeds of the same demo.
    agent_id = (
        "00000000-0000-4000-8000-0000000000b1"
        if billing
        else "00000000-0000-4000-8000-0000000000b2"
    )
    return Agent(
        id=agent_id,
        name=name,
        source=Source.otlp,
        langfuse_connection_id="",
        filter=None,
        environment="production" if billing else "",
        surface_mapping=SurfaceMapping(),
        release_settings=ReleaseSettings(),
        metric_settings=_demo_metrics(name),
        verdict_settings=VerdictSettings(),
        output_format=OutputFormat.text if billing else OutputFormat.json,
        slack_connection_id="",
        is_demo=True,
        created_at=now,
        updated_at=now,
        deleted_at=None,
    )


async def _agents(meta_store: MetaStore, now: datetime) -> dict[str, Agent]:
    found: dict[str, Agent] = {}
    for name in (BILLING, SUPPORT):
        existing = await meta_store.get_agent_by_name(name)
        if existing is None:
            fresh = _demo_agent(name, now)
            # A purge stamps the deleted row with wall-clock time. Seed data is
            # dated at DEMO_CLOCK, which is earlier, so the deleted row would
            # otherwise stay the FINAL version.
            prior = await meta_store.get_agent(fresh.id, include_deleted=True)
            stamp = monotonic_updated_at(
                max(utcnow(), now),
                None if prior is None else prior.updated_at,
            )
            fresh = replace(fresh, updated_at=stamp, deleted_at=None)
            await meta_store.upsert_agent(fresh)
            existing = fresh
        elif not existing.is_demo:
            raise DemoSeedError(f"agent {name} already exists and is not demo")
        found[name] = existing
    return found


async def _flush(event_store: EventStore, rows: list[SpanRow]) -> None:
    if not rows:
        return
    rows.sort(key=lambda row: (row.ingested_at, row.trace_id, row.span_id))
    await write_batch(event_store, rows, rows[-1].ingested_at)
    rows.clear()


async def seed(
    event_store: EventStore,
    meta_store: MetaStore,
    settings: Settings,
    days: int,
    turns_per_day: int,
    seed_value: int,
    now: datetime,
    assembler: Assembler,
) -> dict[str, Any]:
    agents = await _agents(meta_store, now)
    keys = HmacKeys.from_settings(settings)
    buffer: list[SpanRow] = []
    span_count = 0
    for ingest_time, payload in generate(days, turns_per_day, seed_value, now):
        request = parse(json.dumps(payload).encode())
        request_rows: list[SpanRow] = []
        for raw in iter_raw_spans(request):
            agent_name = str(
                raw.attributes.get("gen_ai.agent.name")
                or raw.resource_attributes.get("service.name")
                or ""
            )
            agent = agents[agent_name]
            request_rows.append(
                normalize(
                    raw,
                    source_id="demo",
                    source=Source.otlp,
                    agent_hint=agent.id,
                    now=ingest_time,
                    late_days=settings.late_span_days,
                    keys=keys,
                )
            )
        buffer.extend(request_rows)
        span_count += len(request_rows)
        if len(buffer) >= _BATCH:
            await _flush(event_store, buffer)
    await _flush(event_store, buffer)
    client = getattr(event_store, "client", None)
    for _wave in range(5):
        if client is not None:
            await client.command("SYSTEM FLUSH ASYNC INSERT QUEUE")
        for _ in range(10000):
            if await assembler.run_once(now, limit=_ASSEMBLY_BATCH) == 0:
                break
        else:
            raise RuntimeError("assembly did not finish")
        if client is None:
            break
        pending = await client.query(
            "SELECT count() FROM trace_state FINAL WHERE assembled_at IS NULL"
        )
        if int(pending.result_rows[0][0]) == 0:
            break
    # A worker may already have moved the rollup watermark past the demo clock.
    # Pull it back so the seeded releases get their activity.
    await meta_store.set_setting(
        "rollup.watermark",
        to_iso(now - timedelta(days=days + 1)),
        monotonic_updated_at(now, utcnow()),
    )
    await RollupJob(event_store, meta_store, asyncio.Lock()).run(now)
    await meta_store.set_setting(_SEEDED_AT, to_iso(now), now)
    releases: dict[str, dict[str, int]] = {}
    total = 0
    for name, agent in agents.items():
        counts: dict[str, int] = defaultdict(int)
        for item in await event_store.release_activity(agent.id):
            counts[item.release] = item.turn_count
            total += item.turn_count
        releases[name] = dict(counts)
    return {"agents": releases, "turns": total, "spans": span_count}


async def purge(event_store: EventStore, meta_store: MetaStore, now: datetime) -> int:
    demo_agents = [agent for agent in await meta_store.list_agents() if agent.is_demo]
    for agent in demo_agents:
        await event_store.purge_agent(agent.id, sync=True)
        # Seeding stamps the agent at wall-clock time, which is later than
        # DEMO_CLOCK, so a delete stamped with a demo `now` would lose FINAL.
        stamp = monotonic_updated_at(max(utcnow(), now), agent.updated_at)
        await meta_store.delete_agent(agent.id, stamp)
    await meta_store.delete_setting(_SEEDED_AT, now)
    purge_source = getattr(event_store, "purge_source", None)
    if purge_source is not None:
        await purge_source("demo", sync=True)
    return len(demo_agents)


def _simulation_times(first: datetime, real_now: datetime, max_hours: int) -> list[datetime]:
    final = min(real_now, first + timedelta(hours=max_hours))
    raw = [
        first + timedelta(hours=2),
        first + timedelta(hours=2, minutes=15),
        first + timedelta(hours=24),
        first + timedelta(hours=24, minutes=15),
        final - timedelta(minutes=15),
        final,
    ]
    moments: list[datetime] = []
    for moment in raw:
        if moment < first or moment > real_now:
            continue
        if moments and moment == moments[-1]:
            continue
        moments.append(moment)
    return moments


async def _ensure_releases(
    event_store: EventStore, meta_store: MetaStore, agent: Agent, now: datetime
) -> list[str]:
    from apgar.worker.jobs.release_discovery import new_release

    activity = await event_store.release_activity(agent.id)
    discovered: list[tuple[str, datetime, ReleaseActivity]] = []
    for item in activity:
        if item.release == "untagged":
            continue
        arm = await event_store.load_arm(
            ArmQuery(
                agent_id=agent.id,
                release=item.release,
                window_start=now - timedelta(days=30),
                window_end=now + timedelta(days=1),
                environment=agent.environment,
                include_mixed=True,
                session_min_first_start=None,
                hour_of_day_filter=None,
                now=now,
                count_untagged=False,
            )
        )
        if not arm.turns:
            continue
        first = min(turn.start_ts for turn in arm.turns)
        discovered.append((item.release, first, item))
    discovered.sort(key=lambda row: (row[1], row[0]))
    ordered: list[str] = []
    for index, (name, first, item) in enumerate(discovered):
        existing = await meta_store.get_release(agent.id, name)
        reason = ReasonCode.insufficient_sample if index else ReasonCode.no_baseline
        if existing is None:
            created = new_release(agent.id, name, first, reason, now)
            await meta_store.upsert_release(
                replace(
                    created,
                    last_seen=item.last_seen,
                    turn_count=item.turn_count,
                )
            )
        else:
            await meta_store.upsert_release(
                replace(
                    existing,
                    last_seen=item.last_seen,
                    turn_count=item.turn_count,
                    updated_at=monotonic_updated_at(now, existing.updated_at),
                )
            )
        ordered.append(name)
    return ordered


async def _simulate_agent(
    event_store: EventStore,
    meta_store: MetaStore,
    agent: Agent,
    now: datetime,
    evaluator: Any,
    notify: bool,
) -> dict[str, dict[str, str]]:
    names = await _ensure_releases(event_store, meta_store, agent, now)
    releases = await meta_store.list_releases(
        ReleaseFilters(agent_id=agent.id, limit=100_000, offset=0)
    )
    by_name = {item.release: item for item in releases}
    ordered = sorted(
        (by_name[name] for name in names if name in by_name),
        key=lambda item: item.first_seen,
    )
    agent_states: dict[str, dict[str, str]] = {}
    for release in ordered:
        current = release
        for moment in _simulation_times(
            release.first_seen, now, agent.verdict_settings.max_window_hours
        ):
            await evaluator.evaluate_release(agent, current, moment, False, notify=notify)
            stored = await meta_store.get_release(agent.id, release.release)
            if stored is None:
                break
            current = stored
            if stored.final:
                break
        agent_states[release.release] = {
            "state": current.state.value,
            "reason": current.reason.value,
        }
    return agent_states


async def simulate_verdicts(
    event_store: EventStore,
    meta_store: MetaStore,
    settings: Settings,
    now: datetime,
    evaluator: Any,
    *,
    notify: bool = True,
) -> dict[str, dict[str, dict[str, str]]]:
    agents = [agent for agent in await meta_store.list_agents() if agent.is_demo]
    # Releases of one agent replay in order because each one's baseline depends
    # on the verdicts before it. The agents share nothing, so they run side by
    # side, and a failure cancels the other replay before the job ends.
    try:
        async with asyncio.TaskGroup() as group:
            tasks = [
                group.create_task(
                    _simulate_agent(event_store, meta_store, agent, now, evaluator, notify)
                )
                for agent in agents
            ]
    except ExceptionGroup as failed:
        raise failed.exceptions[0] from failed
    return {agent.name: task.result() for agent, task in zip(agents, tasks, strict=True)}
