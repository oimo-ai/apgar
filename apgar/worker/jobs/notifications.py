from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime, timedelta

import httpx
from prometheus_client import Counter, Gauge

from apgar.actions.errors import PermanentDeliveryError, RetryableDeliveryError
from apgar.actions.slack import send_slack
from apgar.actions.webhook import send_webhook
from apgar.domain.enums import NotificationChannel, NotificationStatus
from apgar.domain.models import Connection, Notification
from apgar.domain.time import monotonic_updated_at
from apgar.storage.interfaces import MetaStore

_LOG = logging.getLogger("apgar.jobs")

BACKOFF_SECONDS = [60, 300, 900, 3600, 21600]
MAX_ATTEMPTS = 5

NOTIFICATIONS = Counter(
    "apgar_notifications_total",
    "Notification delivery attempts by channel and result.",
    ["channel", "result"],
)
FAILED_ROWS = Gauge(
    "apgar_notifications_failed_rows",
    "Notifications currently in the failed status.",
)


class NotificationDispatcher:
    def __init__(
        self,
        meta_store: MetaStore,
        client: httpx.AsyncClient | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._meta = meta_store
        self._client = client
        self._owned = client is None
        self._clock = clock

    async def aclose(self) -> None:
        if self._owned and self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=15)
            self._owned = True
        return self._client

    async def run(self, now: datetime) -> None:
        due = await self._meta.due_notifications(now, limit=50)
        http = await self._http()
        for notification in due:
            attempt_at = now if self._clock is None else self._clock()
            connection = await self._meta.get_connection(notification.connection_id)
            if connection is None:
                await self._store(
                    notification,
                    attempt_at,
                    status=NotificationStatus.failed,
                    attempts=notification.attempts,
                    next_attempt_at=notification.next_attempt_at,
                    last_error="connection missing",
                    result="failed",
                )
                continue
            try:
                await self._send(http, notification, connection, attempt_at)
            except RetryableDeliveryError as exc:
                attempts = notification.attempts + 1
                if attempts >= MAX_ATTEMPTS:
                    await self._store(
                        notification,
                        attempt_at,
                        status=NotificationStatus.failed,
                        attempts=attempts,
                        next_attempt_at=notification.next_attempt_at,
                        last_error=str(exc)[:500],
                        result="failed",
                    )
                else:
                    await self._store(
                        notification,
                        attempt_at,
                        status=NotificationStatus.pending,
                        attempts=attempts,
                        next_attempt_at=attempt_at
                        + timedelta(seconds=BACKOFF_SECONDS[attempts - 1]),
                        last_error=str(exc)[:500],
                        result="retry",
                    )
            except PermanentDeliveryError as exc:
                await self._store(
                    notification,
                    attempt_at,
                    status=NotificationStatus.failed,
                    attempts=notification.attempts + 1,
                    next_attempt_at=notification.next_attempt_at,
                    last_error=str(exc)[:500],
                    result="failed",
                )
            except Exception as exc:
                await self._store(
                    notification,
                    attempt_at,
                    status=NotificationStatus.failed,
                    attempts=notification.attempts + 1,
                    next_attempt_at=notification.next_attempt_at,
                    last_error=str(exc)[:500],
                    result="failed",
                )
            else:
                await self._store(
                    notification,
                    attempt_at,
                    status=NotificationStatus.sent,
                    attempts=notification.attempts,
                    next_attempt_at=notification.next_attempt_at,
                    last_error="",
                    result="sent",
                )
        failed = await self._meta.list_notifications(NotificationStatus.failed, limit=1000)
        FAILED_ROWS.set(len(failed))

    async def _send(
        self,
        http: httpx.AsyncClient,
        notification: Notification,
        connection: Connection,
        now: datetime,
    ) -> None:
        payload = notification.payload
        if notification.channel is NotificationChannel.slack:
            await send_slack(http, str(connection.config["webhook_url"]), payload)
            return
        if notification.channel is NotificationChannel.webhook:
            await send_webhook(
                http,
                str(connection.config["url"]),
                str(connection.config["secret"]),
                payload,
                now,
            )
            return
        raise PermanentDeliveryError(f"unsupported channel {notification.channel.value}")

    async def _store(
        self,
        notification: Notification,
        now: datetime,
        *,
        status: NotificationStatus,
        attempts: int,
        next_attempt_at: datetime,
        last_error: str,
        result: str,
    ) -> None:
        from dataclasses import replace

        updated = replace(
            notification,
            status=status,
            attempts=attempts,
            next_attempt_at=next_attempt_at,
            last_error=last_error,
            updated_at=monotonic_updated_at(now, notification.updated_at),
        )
        await self._meta.upsert_notification(updated)
        NOTIFICATIONS.labels(channel=notification.channel.value, result=result).inc()
