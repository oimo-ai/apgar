from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from apgar.config import Settings
from apgar.domain.enums import (
    NotificationChannel,
    NotificationStatus,
    VerdictState,
)
from apgar.storage.clickhouse.event_store import ClickHouseEventStore
from apgar.storage.clickhouse.meta_store import ClickHouseMetaStore
from tests.factories import (
    make_agent,
    make_evaluation,
    make_job,
    make_notification,
    make_release,
    make_release_event,
)

pytestmark = pytest.mark.integration

_STEP = timedelta(seconds=1)


async def test_settings_set_get_overwrite_delete(
    ch_database: tuple[Settings, ClickHouseEventStore, ClickHouseMetaStore],
    fixed_now: datetime,
) -> None:
    _settings, _event_store, meta = ch_database
    await meta.set_setting("retention.turns_days", "90", fixed_now)
    assert await meta.get_setting("retention.turns_days") == "90"
    await meta.set_setting("retention.turns_days", "30", fixed_now + _STEP)
    await meta.set_setting("telemetry.enabled", "1", fixed_now)
    assert await meta.get_setting("retention.turns_days") == "30"
    assert await meta.list_settings("retention.") == {"retention.turns_days": "30"}
    await meta.delete_setting("retention.turns_days", fixed_now + _STEP + _STEP)
    assert await meta.get_setting("retention.turns_days") is None


async def test_agent_crud_delete_and_finalize(
    ch_database: tuple[Settings, ClickHouseEventStore, ClickHouseMetaStore],
    fixed_now: datetime,
) -> None:
    _settings, _event_store, meta = ch_database
    agent = make_agent(fixed_now)
    await meta.upsert_agent(agent)
    stored = await meta.get_agent_by_name(agent.name)
    assert stored == agent
    deleted_at = fixed_now + _STEP
    await meta.delete_agent(agent.id, deleted_at)
    assert await meta.get_agent_by_name(agent.name) is None
    assert await meta.get_agent(agent.id) is None
    hidden = await meta.get_agent(agent.id, include_deleted=True)
    assert hidden is not None
    assert hidden.deleted_at == deleted_at
    await meta.finalize_agent_deletion(agent.id, deleted_at + _STEP)
    assert await meta.get_agent(agent.id, include_deleted=True) is None


async def test_release_upsert_read_latest(
    ch_database: tuple[Settings, ClickHouseEventStore, ClickHouseMetaStore],
    fixed_now: datetime,
) -> None:
    _settings, _event_store, meta = ch_database
    newer = make_release(
        fixed_now,
        turn_count=5,
        state=VerdictState.FAIL,
        updated_at=fixed_now + timedelta(seconds=2),
    )
    older = make_release(fixed_now, turn_count=1, updated_at=fixed_now)
    await meta.upsert_release(newer)
    await meta.upsert_release(older)
    stored = await meta.get_release(newer.agent_id, newer.release)
    assert stored == newer


async def test_release_events_round_trip(
    ch_database: tuple[Settings, ClickHouseEventStore, ClickHouseMetaStore],
    fixed_now: datetime,
) -> None:
    _settings, _event_store, meta = ch_database
    first = make_release_event(fixed_now, actor="first")
    second = make_release_event(fixed_now + _STEP, actor="second")
    await meta.append_release_event(second)
    await meta.append_release_event(first)
    events = await meta.release_events(first.agent_id, first.release)
    assert events == [first, second]
    assert await meta.release_events_since(fixed_now + _STEP) == [second]


async def test_evaluation_append_and_list_newest_first(
    ch_database: tuple[Settings, ClickHouseEventStore, ClickHouseMetaStore],
    fixed_now: datetime,
) -> None:
    _settings, _event_store, meta = ch_database
    older = make_evaluation(fixed_now, seed="old")
    newer = make_evaluation(fixed_now + _STEP, seed="new", state=VerdictState.PASS)
    await meta.append_evaluation(older)
    await meta.append_evaluation(newer)
    listed = await meta.list_evaluations(older.agent_id, older.release, limit=10)
    assert [item.seed for item in listed] == ["new", "old"]
    assert listed[0] == newer
    later = make_evaluation(fixed_now + _STEP + _STEP, seed="later", state=VerdictState.PASS)
    await meta.append_evaluation(later)
    first = await meta.first_evaluation(older.agent_id, older.release, VerdictState.PASS)
    assert first == newer
    assert await meta.first_evaluation(older.agent_id, older.release, VerdictState.FAIL) is None


async def test_notification_due_and_update(
    ch_database: tuple[Settings, ClickHouseEventStore, ClickHouseMetaStore],
    fixed_now: datetime,
) -> None:
    _settings, _event_store, meta = ch_database
    pending = make_notification(
        fixed_now,
        next_attempt_at=fixed_now - _STEP,
        status=NotificationStatus.pending,
    )
    await meta.upsert_notification(pending)
    due = await meta.due_notifications(fixed_now, 10)
    assert due == [pending]
    sent = make_notification(
        fixed_now,
        next_attempt_at=fixed_now - _STEP,
        status=NotificationStatus.sent,
        attempts=1,
        updated_at=fixed_now + _STEP,
    )
    await meta.upsert_notification(sent)
    assert await meta.due_notifications(fixed_now, 10) == []
    stored = await meta.get_notification(pending.idempotency_key, NotificationChannel.slack)
    assert stored == sent
    assert await meta.list_notifications(None, limit=10, created_since=fixed_now) == [sent]
    assert await meta.list_notifications(None, limit=10, created_since=fixed_now + _STEP) == []


async def test_job_requests_pending_and_complete(
    ch_database: tuple[Settings, ClickHouseEventStore, ClickHouseMetaStore],
) -> None:
    _settings, _event_store, meta = ch_database
    # job_requests expires 7 days after requested_at by the server clock, and a
    # TTL merge can drop an older row before pending_jobs reads it.
    now = datetime.now(UTC).replace(microsecond=0) - timedelta(minutes=1)
    job = make_job(now)
    await meta.enqueue_job(job)
    assert await meta.pending_jobs(10) == [job]
    completed_at = now + _STEP
    await meta.complete_job(job, completed_at)
    assert await meta.pending_jobs(10) == []
