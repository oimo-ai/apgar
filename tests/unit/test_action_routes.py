from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx

from apgar.domain.enums import NotificationStatus
from tests.factories import make_notification
from tests.support import MemStores

NOW = datetime(2026, 10, 8, 9, 30, tzinfo=UTC)


async def test_notification_list_and_retry(
    app_client: httpx.AsyncClient, admin_headers: dict[str, str], mem_stores: MemStores
) -> None:
    _events, meta = mem_stores
    await meta.upsert_notification(
        make_notification(NOW, status=NotificationStatus.failed, attempts=2, last_error="nope")
    )
    listed = await app_client.get(
        "/api/v1/notifications",
        headers=admin_headers,
        params={"status": "failed"},
    )
    assert listed.status_code == 200
    body = listed.json()
    assert body["total"] == 1
    assert body["items"][0]["attempts"] == 2
    retried = await app_client.post(
        f"/api/v1/notifications/{body['items'][0]['id']}/retry",
        headers=admin_headers,
    )
    assert retried.status_code == 202
    stored = await meta.get_notification(
        make_notification(NOW).idempotency_key,
        make_notification(NOW).channel,
    )
    assert stored is not None
    assert stored.attempts == 0
    assert stored.status.value == "pending"
    assert stored.last_error == ""
    sent = make_notification(
        NOW,
        id="sent-note",
        status=NotificationStatus.sent,
        idempotency_key="already-sent",
        updated_at=NOW + timedelta(seconds=1),
        created_at=NOW + timedelta(seconds=1),
    )
    await meta.upsert_notification(sent)
    rejected = await app_client.post(
        f"/api/v1/notifications/{sent.id}/retry",
        headers=admin_headers,
    )
    assert rejected.status_code == 409


async def test_notification_list_pages(
    app_client: httpx.AsyncClient, admin_headers: dict[str, str], mem_stores: MemStores
) -> None:
    _events, meta = mem_stores
    for index in range(3):
        await meta.upsert_notification(
            make_notification(
                NOW,
                id=f"note-{index}",
                idempotency_key=f"key-{index}",
                status=NotificationStatus.failed,
                created_at=NOW + timedelta(seconds=index),
                updated_at=NOW + timedelta(seconds=index),
            )
        )
    first = await app_client.get(
        "/api/v1/notifications", headers=admin_headers, params={"limit": 2, "offset": 0}
    )
    second = await app_client.get(
        "/api/v1/notifications", headers=admin_headers, params={"limit": 2, "offset": 2}
    )
    beyond = await app_client.get(
        "/api/v1/notifications", headers=admin_headers, params={"limit": 2, "offset": 5}
    )
    assert first.json()["total"] == second.json()["total"] == beyond.json()["total"] == 3
    first_ids = [item["id"] for item in first.json()["items"]]
    second_ids = [item["id"] for item in second.json()["items"]]
    assert len(first_ids) == 2
    assert len(second_ids) == 1
    assert sorted(first_ids + second_ids) == ["note-0", "note-1", "note-2"]
    assert beyond.json()["items"] == []
    negative = await app_client.get(
        "/api/v1/notifications", headers=admin_headers, params={"offset": -1}
    )
    assert negative.status_code == 422
