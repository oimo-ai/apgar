from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import httpx
import respx
from prometheus_client import REGISTRY

from apgar.domain.enums import ConnectionType, NotificationStatus
from apgar.worker.jobs.notifications import BACKOFF_SECONDS, MAX_ATTEMPTS, NotificationDispatcher
from tests.factories import make_connection, make_notification
from tests.support import MemStores

NOW = datetime(2026, 10, 8, 9, 30, tzinfo=UTC)
URL = "https://hooks.slack.com/services/T/B/x"


def _counter(result: str) -> float:
    value = REGISTRY.get_sample_value(
        "apgar_notifications_total",
        {"channel": "slack", "result": result},
    )
    return 0.0 if value is None else value


async def _slack(meta: object, note_id: str = "n1") -> None:
    from apgar.storage.memory import InMemoryMetaStore

    assert isinstance(meta, InMemoryMetaStore)
    connection = make_connection(
        NOW,
        id="slack-1",
        type=ConnectionType.slack,
        config={"webhook_url": URL},
    )
    await meta.upsert_connection(connection)
    await meta.upsert_notification(
        make_notification(
            NOW,
            id=note_id,
            connection_id=connection.id,
            payload={"text": "hello"},
            idempotency_key=f"key-{note_id}",
        )
    )


async def test_backoff_constant() -> None:
    assert BACKOFF_SECONDS == [60, 300, 900, 3600, 21600]
    assert MAX_ATTEMPTS == 5


async def test_success_retry_and_permanent(mem_stores: MemStores) -> None:
    _events, meta = mem_stores
    await _slack(meta)
    before = _counter("sent")
    with respx.mock:
        respx.post(URL).mock(return_value=httpx.Response(200, text="ok"))
        dispatcher = NotificationDispatcher(meta)
        await dispatcher.run(NOW)
        await dispatcher.aclose()
    sent = await meta.get_notification("key-n1", make_notification(NOW).channel)
    assert sent is not None
    assert sent.status is NotificationStatus.sent
    assert sent.last_error == ""
    assert _counter("sent") == before + 1

    await meta.upsert_notification(
        make_notification(
            NOW,
            id="n2",
            connection_id="slack-1",
            payload={"text": "again"},
            idempotency_key="key-n2",
            updated_at=NOW + timedelta(seconds=1),
            created_at=NOW + timedelta(seconds=1),
        )
    )
    with respx.mock:
        respx.post(URL).mock(return_value=httpx.Response(500, text="down"))
        dispatcher = NotificationDispatcher(meta)
        current = NOW + timedelta(seconds=1)
        await dispatcher.run(current)
        stored = await meta.get_notification("key-n2", make_notification(NOW).channel)
        assert stored is not None
        assert stored.status is NotificationStatus.pending
        assert stored.attempts == 1
        assert stored.next_attempt_at == current + timedelta(seconds=60)
        stored_attempts = stored
        for index, delay in enumerate(BACKOFF_SECONDS[1:4], start=2):
            current = stored_attempts.next_attempt_at
            await dispatcher.run(current)
            loaded = await meta.get_notification("key-n2", stored_attempts.channel)
            assert loaded is not None
            stored_attempts = loaded
            assert stored_attempts.attempts == index
            assert stored_attempts.next_attempt_at == current + timedelta(seconds=delay)
        await dispatcher.run(stored_attempts.next_attempt_at)
        failed = await meta.get_notification("key-n2", stored_attempts.channel)
        assert failed is not None
        assert failed.status is NotificationStatus.failed
        assert failed.attempts == 5
        await dispatcher.aclose()

    await meta.upsert_notification(
        make_notification(
            NOW,
            id="n3",
            connection_id="slack-1",
            payload={"text": "gone"},
            idempotency_key="key-n3",
            updated_at=NOW + timedelta(seconds=2),
            created_at=NOW + timedelta(seconds=2),
        )
    )
    with respx.mock:
        respx.post(URL).mock(return_value=httpx.Response(404, text="missing"))
        dispatcher = NotificationDispatcher(meta)
        await dispatcher.run(NOW + timedelta(seconds=2))
        await dispatcher.aclose()
    gone = await meta.get_notification("key-n3", make_notification(NOW).channel)
    assert gone is not None
    assert gone.status is NotificationStatus.failed
    assert gone.attempts == 1


async def test_due_selection_skips_future_and_sent(mem_stores: MemStores) -> None:
    _events, meta = mem_stores
    connection = make_connection(
        NOW,
        id="slack-1",
        type=ConnectionType.slack,
        config={"webhook_url": URL},
    )
    await meta.upsert_connection(connection)
    await meta.upsert_notification(
        make_notification(
            NOW,
            id="due",
            connection_id=connection.id,
            idempotency_key="due",
            payload={"text": "due"},
        )
    )
    await meta.upsert_notification(
        make_notification(
            NOW,
            id="later",
            connection_id=connection.id,
            idempotency_key="later",
            payload={"text": "later"},
            next_attempt_at=NOW + timedelta(hours=1),
            updated_at=NOW + timedelta(seconds=1),
            created_at=NOW + timedelta(seconds=1),
        )
    )
    await meta.upsert_notification(
        make_notification(
            NOW,
            id="done",
            connection_id=connection.id,
            idempotency_key="done",
            payload={"text": "done"},
            status=NotificationStatus.sent,
            updated_at=NOW + timedelta(seconds=2),
            created_at=NOW + timedelta(seconds=2),
        )
    )
    with respx.mock:
        route = respx.post(URL).mock(return_value=httpx.Response(200, text="ok"))
        dispatcher = NotificationDispatcher(meta)
        await dispatcher.run(NOW)
        await dispatcher.aclose()
    assert route.call_count == 1
    assert json.loads(route.calls[0].request.content)["text"] == "due"


async def test_missing_connection_fails(mem_stores: MemStores) -> None:
    _events, meta = mem_stores
    await meta.upsert_notification(
        make_notification(NOW, connection_id="missing", idempotency_key="key-missing")
    )
    dispatcher = NotificationDispatcher(meta)
    await dispatcher.run(NOW)
    await dispatcher.aclose()
    stored = await meta.get_notification("key-missing", make_notification(NOW).channel)
    assert stored is not None
    assert stored.status is NotificationStatus.failed
    assert stored.last_error == "connection missing"
    gauge = REGISTRY.get_sample_value("apgar_notifications_failed_rows")
    assert gauge == 1
