from __future__ import annotations

from datetime import datetime, timedelta

from apgar.domain.retention import (
    RETENTION_DEFAULTS,
    RETENTION_TTLS,
    SESSION_LOOKBACK_DAYS,
    min_trace_data_days,
    trace_window_stored,
)
from apgar.domain.settings import BASELINE_DAYS
from apgar.storage.memory import InMemoryEventStore, InMemoryMetaStore
from apgar.worker.jobs.retention import RetentionJob, ttl_statements
from tests.factories import make_agent
from tests.support import make_span, make_turn


class _Client:
    def __init__(self) -> None:
        self.commands: list[str] = []

    async def command(self, sql: str, *args: object, **kwargs: object) -> None:
        del args, kwargs
        self.commands.append(sql)


def test_trace_window_stored_until_the_lookback_ages_out(fixed_now: datetime) -> None:
    assert trace_window_stored(fixed_now, fixed_now + timedelta(days=7), 21)
    assert not trace_window_stored(fixed_now, fixed_now + timedelta(days=8), 21)
    assert trace_window_stored(fixed_now, fixed_now + timedelta(days=76), 90)


def test_minimum_covers_history_baseline_and_monitoring() -> None:
    assert BASELINE_DAYS == 7
    assert SESSION_LOOKBACK_DAYS == 7
    assert min_trace_data_days() == 21


async def test_ttl_statements_once_per_change(fixed_now: datetime) -> None:
    meta = InMemoryMetaStore()
    client = _Client()
    job = RetentionJob(InMemoryEventStore(), meta, client, late_span_days=7)
    await job.run(fixed_now)
    first = len(client.commands)
    assert first == len(RETENTION_TTLS) + 1
    assert any("ALTER TABLE spans MODIFY TTL" in sql for sql in client.commands)
    await job.run(fixed_now + timedelta(seconds=1))
    assert len(client.commands) == first
    await meta.set_setting("retention.trace_data_days", "30", fixed_now + timedelta(seconds=2))
    await job.run(fixed_now + timedelta(seconds=3))
    assert len(client.commands) == first * 2
    latest = client.commands[-first:]
    assert "ALTER TABLE spans MODIFY TTL toDateTime(start_ts) + INTERVAL 30 DAY" in latest
    assert "ALTER TABLE turns MODIFY TTL toDateTime(start_ts) + INTERVAL 30 DAY" in latest
    assert "ALTER TABLE tool_calls MODIFY TTL toDateTime(turn_start_ts) + INTERVAL 30 DAY" in latest
    assert (
        "ALTER TABLE verdict_evaluations MODIFY TTL toDateTime(evaluated_at) + INTERVAL 400 DAY"
        in latest
    )
    assert "ALTER TABLE trace_state MODIFY TTL written_at + INTERVAL 7 DAY" in latest


async def test_late_span_days_reapplies_trace_state(fixed_now: datetime) -> None:
    meta = InMemoryMetaStore()
    client = _Client()
    event = InMemoryEventStore()
    await RetentionJob(event, meta, client, late_span_days=7).run(fixed_now)
    await RetentionJob(event, meta, client, late_span_days=9).run(fixed_now + timedelta(seconds=1))
    assert "ALTER TABLE trace_state MODIFY TTL written_at + INTERVAL 9 DAY" in client.commands


def test_ttl_statement_shape() -> None:
    sql = ttl_statements(dict(RETENTION_DEFAULTS), late_span_days=7)
    assert "ALTER TABLE turns MODIFY TTL toDateTime(start_ts) + INTERVAL 90 DAY" in sql
    assert "ALTER TABLE notifications MODIFY TTL toDateTime(created_at) + INTERVAL 400 DAY" in sql
    assert "ALTER TABLE trace_state MODIFY TTL written_at + INTERVAL 7 DAY" in sql


async def test_deleted_agents_purged_and_finalized(fixed_now: datetime) -> None:
    event = InMemoryEventStore()
    meta = InMemoryMetaStore()
    agent = make_agent(fixed_now)
    await meta.upsert_agent(agent)
    await event.upsert_turns([make_turn(fixed_now, agent_id=agent.id)])
    await meta.delete_agent(agent.id, fixed_now)
    await RetentionJob(event, meta, None, late_span_days=7).run(fixed_now + timedelta(seconds=1))
    assert await meta.get_agent(agent.id, include_deleted=True) is None
    assert all(row.agent_id != agent.id for row in event._turns.values())


async def test_purge_removes_spans_trace_state_no_longer_points_at(fixed_now: datetime) -> None:
    event = InMemoryEventStore()
    meta = InMemoryMetaStore()
    agent = make_agent(fixed_now)
    await meta.upsert_agent(agent)
    hinted = make_span(fixed_now, agent_hint=agent.id, trace_id="ab" * 16, span_id="cd" * 8)
    linked = make_span(
        fixed_now, source_id="src", trace_id="11" * 16, span_id="ee" * 8, agent_hint=""
    )
    other = make_span(fixed_now, agent_hint="someone-else", trace_id="ff" * 16, span_id="12" * 8)
    await event.insert_spans([hinted, linked, other])
    await event.upsert_turns([make_turn(fixed_now, agent_id=agent.id)])
    await meta.delete_agent(agent.id, fixed_now)
    await RetentionJob(event, meta, None, late_span_days=7).run(fixed_now + timedelta(seconds=1))
    assert [row.span_id for row in event._spans.values()] == [other.span_id]
