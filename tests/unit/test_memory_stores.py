from __future__ import annotations

from datetime import timedelta

from apgar.domain.enums import NotificationChannel, NotificationStatus, VerdictState
from apgar.storage.interfaces import EventStore, MetaStore
from apgar.storage.memory import InMemoryEventStore, InMemoryMetaStore
from tests.factories import (
    make_agent,
    make_job,
    make_notification,
    make_release,
    make_release_event,
)

NOW_OFFSET = timedelta(seconds=1)


def test_stores_satisfy_protocols(mem_stores: tuple[InMemoryEventStore, InMemoryMetaStore]) -> None:
    event_store, meta_store = mem_stores
    assert isinstance(event_store, EventStore)
    assert isinstance(meta_store, MetaStore)


async def test_settings_crud(
    mem_stores: tuple[InMemoryEventStore, InMemoryMetaStore],
    fixed_now: object,
) -> None:
    from datetime import datetime

    assert isinstance(fixed_now, datetime)
    _event_store, meta = mem_stores
    later = fixed_now + NOW_OFFSET
    await meta.set_setting("retention.days", "90", fixed_now)
    assert await meta.get_setting("retention.days") == "90"
    await meta.set_setting("retention.days", "30", later)
    await meta.set_setting("telemetry.enabled", "1", fixed_now)
    assert await meta.get_setting("retention.days") == "30"
    assert await meta.list_settings("retention.") == {"retention.days": "30"}
    await meta.delete_setting("retention.days", later + NOW_OFFSET)
    assert await meta.get_setting("retention.days") is None


async def test_agent_delete_sets_deleted_at_and_hides_row(
    mem_stores: tuple[InMemoryEventStore, InMemoryMetaStore],
    fixed_now: object,
) -> None:
    from datetime import datetime

    assert isinstance(fixed_now, datetime)
    _event_store, meta = mem_stores
    agent = make_agent(fixed_now)
    await meta.upsert_agent(agent)
    deleted_at = fixed_now + NOW_OFFSET
    await meta.delete_agent(agent.id, deleted_at)
    assert await meta.get_agent_by_name(agent.name) is None
    assert all(item.id != agent.id for item in await meta.list_agents())
    hidden = await meta.get_agent(agent.id)
    assert hidden is None
    visible = await meta.get_agent(agent.id, include_deleted=True)
    assert visible is not None
    assert visible.deleted_at == deleted_at
    listed = await meta.list_agents(include_deleted=True)
    assert any(item.id == agent.id for item in listed)


async def test_finalize_agent_deletion_marks_is_deleted(
    mem_stores: tuple[InMemoryEventStore, InMemoryMetaStore],
    fixed_now: object,
) -> None:
    from datetime import datetime

    assert isinstance(fixed_now, datetime)
    _event_store, meta = mem_stores
    agent = make_agent(fixed_now)
    await meta.upsert_agent(agent)
    await meta.delete_agent(agent.id, fixed_now + NOW_OFFSET)
    await meta.finalize_agent_deletion(agent.id, fixed_now + NOW_OFFSET + NOW_OFFSET)
    assert await meta.get_agent(agent.id, include_deleted=True) is None
    assert await meta.list_agents(include_deleted=True) == []


async def test_release_upsert_latest_wins(
    mem_stores: tuple[InMemoryEventStore, InMemoryMetaStore],
    fixed_now: object,
) -> None:
    from datetime import datetime

    assert isinstance(fixed_now, datetime)
    _event_store, meta = mem_stores
    newer = make_release(
        fixed_now,
        turn_count=4,
        state=VerdictState.FAIL,
        updated_at=fixed_now + timedelta(seconds=2),
    )
    older = make_release(fixed_now, turn_count=9, updated_at=fixed_now + NOW_OFFSET)
    await meta.upsert_release(newer)
    await meta.upsert_release(older)
    stored = await meta.get_release(newer.agent_id, newer.release)
    assert stored is not None
    assert stored.turn_count == 4
    assert stored.state == VerdictState.FAIL


async def test_release_events_append_order(
    mem_stores: tuple[InMemoryEventStore, InMemoryMetaStore],
    fixed_now: object,
) -> None:
    from datetime import datetime

    assert isinstance(fixed_now, datetime)
    _event_store, meta = mem_stores
    first = make_release_event(fixed_now, actor="first")
    second = make_release_event(fixed_now + NOW_OFFSET, actor="second")
    await meta.append_release_event(first)
    await meta.append_release_event(second)
    events = await meta.release_events(first.agent_id, first.release)
    assert [event.actor for event in events] == ["first", "second"]


async def test_job_queue_enqueue_pending_complete(
    mem_stores: tuple[InMemoryEventStore, InMemoryMetaStore],
    fixed_now: object,
) -> None:
    from datetime import datetime

    assert isinstance(fixed_now, datetime)
    _event_store, meta = mem_stores
    first = make_job(fixed_now, id="job-1")
    second = make_job(fixed_now, id="job-2")
    await meta.enqueue_job(first)
    await meta.enqueue_job(second)
    assert {job.id for job in await meta.pending_jobs(10)} == {"job-1", "job-2"}
    await meta.complete_job(first, fixed_now + NOW_OFFSET)
    pending = await meta.pending_jobs(10)
    assert [job.id for job in pending] == ["job-2"]
    assert pending[0].processed_at is None


async def test_notification_upsert_by_key_and_channel(
    mem_stores: tuple[InMemoryEventStore, InMemoryMetaStore],
    fixed_now: object,
) -> None:
    from datetime import datetime

    assert isinstance(fixed_now, datetime)
    _event_store, meta = mem_stores
    slack = make_notification(fixed_now, channel=NotificationChannel.slack, attempts=1)
    webhook = make_notification(
        fixed_now,
        id="00000000-0000-4000-8000-0000000000n2",
        channel=NotificationChannel.webhook,
        attempts=1,
    )
    await meta.upsert_notification(slack)
    await meta.upsert_notification(webhook)
    updated = make_notification(
        fixed_now,
        channel=NotificationChannel.slack,
        attempts=3,
        status=NotificationStatus.sent,
        updated_at=fixed_now + NOW_OFFSET,
    )
    await meta.upsert_notification(updated)
    stored_slack = await meta.get_notification(slack.idempotency_key, NotificationChannel.slack)
    stored_webhook = await meta.get_notification(slack.idempotency_key, NotificationChannel.webhook)
    assert stored_slack is not None and stored_slack.attempts == 3
    assert stored_webhook is not None and stored_webhook.attempts == 1


async def test_returned_rows_are_isolated_from_later_mutation(
    mem_stores: tuple[InMemoryEventStore, InMemoryMetaStore],
    fixed_now: object,
) -> None:
    from datetime import datetime

    from apgar.domain.enums import SpanKind, SpanStatus
    from apgar.domain.models import SpanRow

    assert isinstance(fixed_now, datetime)
    event_store, meta = mem_stores
    release = make_release(fixed_now, verdict_summary={"status": "PENDING"})
    await meta.upsert_release(release)
    release.turn_count = 99
    release.verdict_summary["status"] = "changed"
    stored = await meta.get_release(release.agent_id, release.release)
    assert stored is not None
    assert stored.turn_count == 0
    assert stored.verdict_summary == {"status": "PENDING"}
    stored.turn_count = 7
    stored.verdict_summary["extra"] = "1"
    again = await meta.get_release(release.agent_id, release.release)
    assert again is not None
    assert again.turn_count == 0
    assert again.verdict_summary == {"status": "PENDING"}

    span = SpanRow(
        source_id="src",
        trace_id="a" * 32,
        span_id="b" * 16,
        parent_span_id="",
        kind=SpanKind.chat,
        name="chat",
        start_ts=fixed_now,
        end_ts=fixed_now,
        status=SpanStatus.ok,
        error_type="",
        agent_hint="",
        attributes={"agent.name": "billing"},
        request_model="",
        response_model="",
        input_tokens=None,
        output_tokens=None,
        cost_usd=None,
        tool_name="",
        tool_call_id="",
        args_hash="",
        output_chars=None,
        output_json_valid=None,
        late=False,
        ingested_at=fixed_now,
    )
    await event_store.insert_spans([span])
    span.attributes["agent.name"] = "mutated"
    found = await event_store.spans_of_trace("src", "a" * 32)
    assert found[0].attributes["agent.name"] == "billing"
