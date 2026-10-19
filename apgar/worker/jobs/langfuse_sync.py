from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime
from typing import Any

import httpx

from apgar.config import Settings
from apgar.connectors.langfuse.client import LangfuseClient
from apgar.connectors.langfuse.sync import LangfuseSync
from apgar.domain.enums import ConnectionType
from apgar.domain.models import Connection
from apgar.domain.time import utcnow
from apgar.normalize.normalizer import HmacKeys
from apgar.storage.interfaces import EventStore, MetaStore

_LOG = logging.getLogger("apgar.langfuse")


def config_hash(config: dict[str, Any]) -> str:
    payload = json.dumps(config, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


class LangfuseSyncJob:
    def __init__(
        self,
        event_store: EventStore,
        meta_store: MetaStore,
        settings: Settings,
        keys: HmacKeys,
    ) -> None:
        self._events = event_store
        self._meta = meta_store
        self._settings = settings
        self._keys = keys
        self._runners: dict[str, LangfuseSync] = {}
        self._hashes: dict[str, str] = {}
        self._clients: dict[str, httpx.AsyncClient] = {}
        self._retired: list[httpx.AsyncClient] = []

    async def _drain(self) -> None:
        retired = self._retired
        self._retired = []
        for client in retired:
            await client.aclose()

    async def aclose(self) -> None:
        await self._drain()
        clients = list(self._clients.values())
        self._clients.clear()
        for client in clients:
            await client.aclose()

    def _runner(self, connection: Connection) -> LangfuseSync:
        digest = config_hash(connection.config)
        current = self._runners.get(connection.id)
        if current is not None and self._hashes.get(connection.id) == digest:
            current.connection = connection
            return current
        stale = self._clients.pop(connection.id, None)
        if stale is not None:
            self._retired.append(stale)
        http = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=10, read=60, write=10, pool=10),
            auth=(
                str(connection.config.get("public_key", "")),
                str(connection.config.get("secret_key", "")),
            ),
        )
        self._clients[connection.id] = http
        flag = True if current is None else current.any_of_supported
        runner = LangfuseSync(
            connection,
            LangfuseClient(
                str(connection.config.get("host", "")),
                str(connection.config.get("public_key", "")),
                str(connection.config.get("secret_key", "")),
                http,
                utcnow,
                connection.name,
            ),
            self._events,
            self._meta,
            self._settings,
            self._keys,
        )
        runner.any_of_supported = flag
        self._runners[connection.id] = runner
        self._hashes[connection.id] = digest
        return runner

    async def run(self, now: datetime) -> None:
        await self._drain()
        connections = [
            item
            for item in await self._meta.list_connections()
            if item.type is ConnectionType.langfuse
        ]
        failed: Exception | None = None
        for connection in connections:
            try:
                await self._runner(connection).run_cycle(now)
            except Exception as exc:
                _LOG.exception("langfuse sync failed", extra={"connection": connection.name})
                failed = exc
        if failed is not None:
            raise failed
