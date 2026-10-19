from __future__ import annotations

import logging
from datetime import datetime

import httpx
from prometheus_client import Counter

from apgar.config import Settings
from apgar.storage.interfaces import EventStore, MetaStore
from apgar.telemetry import build_payload, report_day, telemetry_is_enabled

_LOG = logging.getLogger("apgar.telemetry")

ATTEMPTS = Counter(
    "apgar_telemetry_attempts_total",
    "Daily telemetry delivery attempts.",
    ["result"],
)


class TelemetryJob:
    def __init__(
        self,
        event_store: EventStore,
        meta_store: MetaStore,
        settings: Settings,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._events = event_store
        self._meta = meta_store
        self._settings = settings
        self._client = client
        self._owned: httpx.AsyncClient | None = None

    async def _http(self) -> httpx.AsyncClient:
        if self._client is not None:
            return self._client
        if self._owned is None:
            self._owned = httpx.AsyncClient(timeout=5.0)
        return self._owned

    async def aclose(self) -> None:
        if self._owned is not None:
            await self._owned.aclose()
            self._owned = None

    async def run(self, now: datetime) -> None:
        if not await telemetry_is_enabled(self._settings, self._meta):
            return
        today = report_day(now)
        last_sent = await self._meta.get_setting("telemetry.last_sent_date")
        last_attempt = await self._meta.get_setting("telemetry.last_attempt_date")
        if last_sent == today or last_attempt == today:
            return
        await self._meta.set_setting("telemetry.last_attempt_date", today, now)
        endpoint = await self._meta.get_setting("telemetry.endpoint")
        target = endpoint or self._settings.telemetry_endpoint
        payload = await build_payload(self._meta, self._events, self._settings, now)
        try:
            response = await (await self._http()).post(target, json=payload)
        except httpx.HTTPError as exc:
            ATTEMPTS.labels(result="error").inc()
            _LOG.debug("telemetry post failed", extra={"error": type(exc).__name__})
            return
        if 200 <= response.status_code < 300:
            await self._meta.set_setting("telemetry.last_sent_date", today, now)
            ATTEMPTS.labels(result="sent").inc()
            return
        ATTEMPTS.labels(result="error").inc()
        _LOG.debug("telemetry post failed", extra={"status": response.status_code})
