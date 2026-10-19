from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from uuid import uuid4

from apgar.actions.messages import slack_message, webhook_payload
from apgar.config import Settings
from apgar.domain.enums import (
    ConnectionType,
    NotificationChannel,
    NotificationEvent,
    NotificationStatus,
    ReasonCode,
    VerdictState,
)
from apgar.domain.models import Agent, Connection, Notification, Release
from apgar.domain.time import to_iso
from apgar.storage.interfaces import MetaStore
from apgar.storage.types import ReleaseActivity, ReleaseFilters
from apgar.verdict.baseline import select_baseline
from apgar.verdict.evaluate import TransitionEvent
from apgar.verdict.state_machine import fold_events
from apgar.verdict.summary import pending_summary


def _summary(agent: Agent, release: Release, settings: Settings) -> dict[str, object]:
    if release.verdict_summary:
        return release.verdict_summary
    return pending_summary(agent, release, settings)


def _event_names(ev: TransitionEvent) -> list[NotificationEvent]:
    names: list[NotificationEvent] = []
    if ev.new_state is VerdictState.FAIL and ev.prev_state is not VerdictState.FAIL:
        names.append(NotificationEvent.regression)
    if (
        ev.new_state is VerdictState.PASS
        and ev.prev_state is not VerdictState.PASS
        and ev.agent.verdict_settings.notify_healthy
    ):
        names.append(NotificationEvent.healthy)
    if (
        ev.became_final
        and ev.new_state is VerdictState.INCONCLUSIVE
        and ev.new_reason in {ReasonCode.window_elapsed, ReasonCode.stopped}
    ):
        names.append(NotificationEvent.ended)
    return names


class TransitionEmitter:
    def __init__(
        self,
        meta_store: MetaStore,
        settings: Settings,
        clock: Callable[[], datetime],
    ) -> None:
        self._meta = meta_store
        self._settings = settings
        self._clock = clock

    async def on_transition(self, ev: TransitionEvent) -> None:
        names = _event_names(ev)
        if not names:
            return
        key_at = ev.evaluation.evaluated_at
        queued_at = key_at if key_at >= self._clock() else self._clock()
        summary = _summary(ev.agent, ev.release, self._settings)
        base = (
            f"{ev.agent.name}:{ev.release.release}:{ev.prev_state.value}->{ev.new_state.value}:"
            f"{to_iso(key_at)}"
        )
        for index, event in enumerate(names):
            key = base if index == 0 else f"{base}:{event.value}"
            await self._fanout(event, key, ev.agent, ev.release, summary, queued_at, ev.prev_state)

    async def on_registered(self, agent: Agent, release: Release) -> None:
        now = self._clock()
        summary = _summary(agent, release, self._settings)
        releases = await self._meta.list_releases(ReleaseFilters(agent_id=agent.id, limit=100_000))
        activity = {
            row.release: ReleaseActivity(row.release, row.last_seen, row.turn_count)
            for row in releases
            if row.last_seen is not None
        }
        choice = select_baseline(release, releases, fold_events([]), activity, now)
        detected = {
            **summary,
            "baseline": {
                "release": None if choice is None else choice.release,
                "mode": None if choice is None else choice.reported_mode,
                "unverified": False if choice is None else choice.unverified,
            },
        }
        event = NotificationEvent.release_detected
        key = f"{agent.name}:{release.release}:{event.value}"
        await self._fanout(event, key, agent, release, detected, now, None)

    async def _fanout(
        self,
        event: NotificationEvent,
        base_key: str,
        agent: Agent,
        release: Release,
        summary: dict[str, object],
        now: datetime,
        previous_verdict: VerdictState | None,
    ) -> None:
        message = slack_message(event, agent, release, summary)
        if agent.slack_connection_id:
            await put_notification(
                self._meta,
                _pending(
                    agent,
                    release,
                    event,
                    base_key,
                    NotificationChannel.slack,
                    agent.slack_connection_id,
                    message,
                    now,
                ),
            )
        for connection in await webhook_connections(self._meta):
            payload = webhook_payload(
                event,
                agent,
                release,
                summary,
                str(message["text"]),
                now,
                agent.is_demo,
                idempotency_key=base_key,
                previous_verdict=previous_verdict,
            )
            await put_notification(
                self._meta,
                _pending(
                    agent,
                    release,
                    event,
                    f"{base_key}:{connection.id}",
                    NotificationChannel.webhook,
                    connection.id,
                    payload,
                    now,
                ),
            )


def _pending(
    agent: Agent,
    release: Release,
    event: NotificationEvent,
    idempotency_key: str,
    channel: NotificationChannel,
    connection_id: str,
    payload: dict[str, object],
    now: datetime,
) -> Notification:
    return Notification(
        id=str(uuid4()),
        agent_id=agent.id,
        release=release.release,
        event=event,
        idempotency_key=idempotency_key,
        channel=channel,
        connection_id=connection_id,
        status=NotificationStatus.pending,
        attempts=0,
        next_attempt_at=now,
        last_error="",
        payload=payload,
        created_at=now,
        updated_at=now,
    )


async def put_notification(meta: MetaStore, notification: Notification) -> bool:
    existing = await meta.get_notification(notification.idempotency_key, notification.channel)
    if existing is not None:
        return False
    await meta.upsert_notification(notification)
    return True


async def webhook_connections(meta: MetaStore) -> list[Connection]:
    return [item for item in await meta.list_connections() if item.type is ConnectionType.webhook]
