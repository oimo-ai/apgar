from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest
import respx

from apgar.domain.enums import ConnectionType, NotificationStatus
from apgar.worker.jobs.notifications import NotificationDispatcher
from tests.factories import make_connection, make_notification
from tests.support import ChDatabase

pytestmark = pytest.mark.integration

NOW = datetime(2026, 10, 8, 9, 30, tzinfo=UTC)
URL = "https://hooks.slack.com/services/T/B/x"


async def test_delivery_persists_and_is_not_resent(ch_database: ChDatabase) -> None:
    _settings, _events, meta = ch_database
    connection = make_connection(
        NOW,
        id="slack-1",
        type=ConnectionType.slack,
        config={"webhook_url": URL},
    )
    await meta.upsert_connection(connection)
    note = make_notification(
        NOW,
        connection_id=connection.id,
        payload={"text": "hello"},
        idempotency_key="billing:rel:PENDING->FAIL:2026-10-08T09:30:00.000Z",
    )
    await meta.upsert_notification(note)
    with respx.mock:
        respx.post(URL).mock(return_value=httpx.Response(200, text="ok"))
        dispatcher = NotificationDispatcher(meta)
        await dispatcher.run(NOW)
        await dispatcher.aclose()
    stored = await meta.get_notification(note.idempotency_key, note.channel)
    assert stored is not None
    assert stored.status is NotificationStatus.sent
    with respx.mock:
        route = respx.post(URL).mock(return_value=httpx.Response(200, text="ok"))
        restarted = NotificationDispatcher(meta)
        await restarted.run(NOW + timedelta(seconds=5))
        await restarted.aclose()
    assert not route.called


async def test_failing_receiver_advances_attempts(ch_database: ChDatabase) -> None:
    _settings, _events, meta = ch_database
    connection = make_connection(
        NOW,
        id="slack-1",
        type=ConnectionType.slack,
        config={"webhook_url": URL},
    )
    await meta.upsert_connection(connection)
    note = make_notification(NOW, connection_id=connection.id, payload={"text": "hello"})
    await meta.upsert_notification(note)
    clock = NOW
    with respx.mock:
        respx.post(URL).mock(return_value=httpx.Response(503, text="down"))
        dispatcher = NotificationDispatcher(meta)
        for _ in range(3):
            await dispatcher.run(clock)
            stored = await meta.get_notification(note.idempotency_key, note.channel)
            assert stored is not None
            clock = stored.next_attempt_at
        await dispatcher.aclose()
    stored = await meta.get_notification(note.idempotency_key, note.channel)
    assert stored is not None
    assert stored.attempts == 3
    assert stored.status is NotificationStatus.pending
    assert stored.next_attempt_at > NOW
