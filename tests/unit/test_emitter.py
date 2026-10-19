from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

from apgar.actions.dispatcher import TransitionEmitter
from apgar.domain.enums import (
    ConnectionType,
    NotificationChannel,
    NotificationEvent,
    ReasonCode,
    VerdictState,
)
from apgar.domain.models import Agent
from apgar.verdict.evaluate import TransitionEvent
from tests.factories import make_agent, make_connection, make_evaluation, make_release
from tests.support import MemStores

NOW = datetime(2026, 10, 8, 9, 30, tzinfo=UTC)


def _summary(verdict: str, reason: str) -> dict[str, object]:
    return {
        "verdict": verdict,
        "reason": reason,
        "final": False,
        "ok": verdict == "PASS",
        "baseline": {"release": "base", "mode": "previous_release", "unverified": False},
        "sample": {"candidate_turns": 10, "baseline_turns": 12},
        "failed_metrics": [],
        "report_url": "http://localhost:8080/agents/billing-copilot/releases/rel",
    }


def _event(
    agent: Agent,
    *,
    release: str = "rel",
    prev: VerdictState = VerdictState.PENDING,
    new: VerdictState = VerdictState.INCONCLUSIVE,
    prev_reason: ReasonCode = ReasonCode.no_baseline,
    new_reason: ReasonCode = ReasonCode.insufficient_sample,
    final: bool = False,
    became_final: bool = False,
) -> TransitionEvent:
    row = make_release(
        NOW,
        agent_id=agent.id,
        release=release,
        state=new,
        reason=new_reason,
        final=final,
        verdict_summary=_summary(new.value, new_reason.value),
    )
    evaluation = make_evaluation(
        NOW,
        agent_id=agent.id,
        release=release,
        state=new,
        reason=new_reason,
        evaluated_at=NOW,
    )
    return TransitionEvent(
        agent, row, prev, prev_reason, new, new_reason, evaluation, final, became_final
    )


async def test_transition_events_and_idempotency(settings: object, mem_stores: MemStores) -> None:
    from apgar.config import Settings

    assert isinstance(settings, Settings)
    _events, meta = mem_stores
    slack = make_connection(
        NOW,
        id="slack-1",
        name="slack",
        type=ConnectionType.slack,
        config={"webhook_url": "https://hooks.slack.com/services/T/B/x"},
    )
    hook_a = make_connection(
        NOW,
        id="hook-a",
        name="hook-a",
        type=ConnectionType.webhook,
        config={"url": "https://example.test/a", "secret": "s" * 16},
    )
    hook_b = make_connection(
        NOW + timedelta(seconds=1),
        id="hook-b",
        name="hook-b",
        type=ConnectionType.webhook,
        config={"url": "https://example.test/b", "secret": "s" * 16},
    )
    for connection in (slack, hook_a, hook_b):
        await meta.upsert_connection(connection)
    agent = make_agent(NOW, slack_connection_id=slack.id)
    await meta.upsert_agent(agent)
    emitter = TransitionEmitter(meta, settings, lambda: NOW)
    base = make_release(
        NOW - timedelta(days=2),
        agent_id=agent.id,
        release="base",
        state=VerdictState.PASS,
        reason=ReasonCode.confirmed,
    )
    detected = make_release(NOW, agent_id=agent.id, release="rel", state=VerdictState.PENDING)
    await meta.upsert_release(base)
    await emitter.on_registered(agent, detected)
    await emitter.on_registered(agent, detected)
    await emitter.on_transition(_event(agent))
    rows = await meta.list_notifications(None, limit=20)
    slack_rows = [row for row in rows if row.channel is NotificationChannel.slack]
    assert len(slack_rows) == 1
    assert slack_rows[0].event is NotificationEvent.release_detected
    assert "New release detected. Comparing with base." in str(slack_rows[0].payload["text"])
    assert slack_rows[0].payload["blocks"] == [
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": "*New release* · billing-copilot · release `rel`"},
        }
    ]
    assert slack_rows[0].payload["attachments"][0]["color"] == "#1D5EA8"
    hooks = [row for row in rows if row.channel is NotificationChannel.webhook]
    assert len(hooks) == 2
    assert {row.idempotency_key.rsplit(":", 1)[-1] for row in hooks} == {"hook-a", "hook-b"}
    detected_key = "billing-copilot:rel:release_detected"
    assert {row.payload["idempotency_key"] for row in hooks} == {detected_key}
    assert all(row.payload["previous_verdict"] is None for row in hooks)
    for row in hooks:
        verdict = row.payload["verdict"]
        assert isinstance(verdict, dict)
        assert not {"agent", "release", "ok", "excluded"} & set(verdict)
        assert verdict["baseline"] == {
            "release": "base",
            "mode": "previous_release",
            "unverified": False,
        }
    fail = _event(
        agent,
        prev=VerdictState.INCONCLUSIVE,
        new=VerdictState.FAIL,
        prev_reason=ReasonCode.fail_candidate,
        new_reason=ReasonCode.confirmed,
        release="a1b2c3d",
    )
    await emitter.on_transition(fail)
    await emitter.on_transition(fail)
    again = await meta.list_notifications(None, limit=20)
    fail_slack = [
        row
        for row in again
        if row.channel is NotificationChannel.slack and row.event is NotificationEvent.regression
    ]
    assert len(fail_slack) == 1
    fail_hooks = [
        row
        for row in again
        if row.channel is NotificationChannel.webhook and row.event is NotificationEvent.regression
    ]
    assert len(fail_hooks) == 2
    for row in fail_hooks:
        assert row.payload["previous_verdict"] == "INCONCLUSIVE"
        assert row.payload["idempotency_key"] == (
            "billing-copilot:a1b2c3d:INCONCLUSIVE->FAIL:2026-10-08T09:30:00.000Z"
        )
        assert row.idempotency_key == f"{row.payload['idempotency_key']}:{row.connection_id}"


async def test_demo_agent_webhook_is_labeled(settings: object, mem_stores: MemStores) -> None:
    from apgar.config import Settings

    assert isinstance(settings, Settings)
    _events, meta = mem_stores
    slack = make_connection(
        NOW,
        id="slack-1",
        type=ConnectionType.slack,
        config={"webhook_url": "https://hooks.slack.com/services/T/B/x"},
    )
    hook = make_connection(
        NOW,
        id="hook-a",
        type=ConnectionType.webhook,
        config={"url": "https://example.test/a", "secret": "s" * 16},
    )
    for connection in (slack, hook):
        await meta.upsert_connection(connection)
    agent = make_agent(NOW, is_demo=True, slack_connection_id=slack.id)
    await meta.upsert_agent(agent)
    emitter = TransitionEmitter(meta, settings, lambda: NOW)
    await emitter.on_transition(
        _event(
            agent,
            release="a1b2c3d",
            new=VerdictState.FAIL,
            prev=VerdictState.PENDING,
        )
    )
    rows = await meta.list_notifications(None, limit=10)
    webhook = next(row for row in rows if row.channel is NotificationChannel.webhook)
    assert webhook.payload["demo"] is True


async def test_reopened_fail_that_passes_sends_healthy(
    settings: object, mem_stores: MemStores
) -> None:
    from apgar.config import Settings

    assert isinstance(settings, Settings)
    _events, meta = mem_stores
    slack = make_connection(
        NOW,
        type=ConnectionType.slack,
        config={"webhook_url": "https://hooks.slack.com/services/T/B/x"},
    )
    await meta.upsert_connection(slack)
    agent = make_agent(NOW, slack_connection_id=slack.id)
    await meta.upsert_agent(agent)
    emitter = TransitionEmitter(meta, settings, lambda: NOW)
    await emitter.on_transition(
        _event(
            agent,
            prev=VerdictState.FAIL,
            new=VerdictState.PASS,
            prev_reason=ReasonCode.confirmed,
            new_reason=ReasonCode.confirmed,
        )
    )
    rows = await meta.list_notifications(None, limit=5)
    assert rows[0].event is NotificationEvent.healthy
    assert "Healthy. No regression" in str(rows[0].payload["text"])


async def test_no_slack_without_connection(settings: object, mem_stores: MemStores) -> None:
    from apgar.config import Settings

    assert isinstance(settings, Settings)
    _events, meta = mem_stores
    agent = make_agent(NOW)
    await meta.upsert_agent(agent)
    emitter = TransitionEmitter(meta, settings, lambda: NOW)
    await emitter.on_transition(
        _event(
            agent,
            prev=VerdictState.INCONCLUSIVE,
            new=VerdictState.PASS,
            new_reason=ReasonCode.confirmed,
        )
    )
    assert await meta.list_notifications(None, limit=10) == []


async def _ended_rows(
    settings: object, mem_stores: MemStores, reason: ReasonCode
) -> list[NotificationEvent]:
    from apgar.config import Settings

    assert isinstance(settings, Settings)
    _events, meta = mem_stores
    slack = make_connection(
        NOW,
        type=ConnectionType.slack,
        config={"webhook_url": "https://hooks.slack.com/services/T/B/x"},
    )
    await meta.upsert_connection(slack)
    agent = make_agent(NOW, slack_connection_id=slack.id)
    await meta.upsert_agent(agent)
    emitter = TransitionEmitter(meta, settings, lambda: NOW)
    await emitter.on_transition(
        _event(
            agent,
            prev=VerdictState.INCONCLUSIVE,
            new=VerdictState.INCONCLUSIVE,
            prev_reason=ReasonCode.insufficient_power,
            new_reason=reason,
            final=True,
            became_final=True,
        )
    )
    return [row.event for row in await meta.list_notifications(None, limit=5)]


async def test_ended_is_sent_for_window_but_not_takeover(
    settings: object, mem_stores: MemStores
) -> None:
    assert await _ended_rows(settings, mem_stores, ReasonCode.window_elapsed) == [
        NotificationEvent.ended
    ]


async def test_stop_sends_ended(settings: object, mem_stores: MemStores) -> None:
    assert await _ended_rows(settings, mem_stores, ReasonCode.stopped) == [NotificationEvent.ended]


async def test_takeover_end_is_silent(settings: object, mem_stores: MemStores) -> None:
    assert await _ended_rows(settings, mem_stores, ReasonCode.superseded) == []


async def test_healthy_can_be_turned_off(settings: object, mem_stores: MemStores) -> None:
    from apgar.config import Settings

    assert isinstance(settings, Settings)
    _events, meta = mem_stores
    slack = make_connection(
        NOW,
        type=ConnectionType.slack,
        config={"webhook_url": "https://hooks.slack.com/services/T/B/x"},
    )
    await meta.upsert_connection(slack)
    agent = make_agent(NOW, slack_connection_id=slack.id)
    quiet = replace(
        agent, verdict_settings=agent.verdict_settings.model_copy(update={"notify_healthy": False})
    )
    emitter = TransitionEmitter(meta, settings, lambda: NOW)
    event = _event(
        quiet,
        prev=VerdictState.INCONCLUSIVE,
        new=VerdictState.PASS,
        new_reason=ReasonCode.confirmed,
    )
    await emitter.on_transition(event)
    assert await meta.list_notifications(None, limit=5) == []
    await emitter.on_transition(replace(event, agent=agent))
    rows = await meta.list_notifications(None, limit=5)
    assert [row.event for row in rows] == [NotificationEvent.healthy]
