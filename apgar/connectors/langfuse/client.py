from __future__ import annotations

import asyncio
import random
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import httpx
from prometheus_client import Counter

from apgar import __version__

REQUESTS = Counter(
    "apgar_langfuse_requests_total",
    "Langfuse HTTP requests.",
    ["connection", "status"],
)
_MAX_ATTEMPTS = 8


class LangfuseError(Exception):
    pass


class LangfuseRateLimited(LangfuseError):
    pass


class LangfuseServerError(LangfuseError):
    pass


class LangfuseClientError(LangfuseError):
    def __init__(self, status_code: int, body_text: str) -> None:
        super().__init__(f"HTTP {status_code}: {body_text}")
        self.status_code = status_code
        self.body_text = body_text


@dataclass(frozen=True, slots=True)
class ObservationsPage:
    data: list[dict[str, Any]]
    cursor: str | None


class LangfuseClient:
    def __init__(
        self,
        host: str,
        public_key: str,
        secret_key: str,
        http: httpx.AsyncClient,
        clock: Callable[[], datetime],
        connection: str,
    ) -> None:
        self._host = host.rstrip("/")
        self._public_key = public_key
        self._secret_key = secret_key
        self._http = http
        self._clock = clock
        self._connection = connection

    def _count(self, status: str) -> None:
        REQUESTS.labels(connection=self._connection, status=status).inc()

    def _delay(self, attempt: int, retry_after: str | None) -> float:
        if retry_after:
            try:
                return float(retry_after)
            except ValueError:
                pass
        return min(60.0, float(2**attempt)) + random.uniform(0, 1)

    async def _send(
        self, method: str, path: str, params: list[tuple[str, str]] | None
    ) -> httpx.Response:
        last_status = 0
        for attempt in range(_MAX_ATTEMPTS):
            try:
                query: Any = params
                response = await self._http.request(
                    method,
                    self._host + path,
                    params=query,
                    auth=(self._public_key, self._secret_key),
                    headers={
                        "Accept": "application/json",
                        "User-Agent": f"apgar/{__version__}",
                    },
                )
            except httpx.TransportError as exc:
                self._count("transport")
                if attempt == _MAX_ATTEMPTS - 1:
                    raise LangfuseServerError(str(exc)) from exc
                await asyncio.sleep(self._delay(attempt, None))
                continue
            last_status = response.status_code
            self._count(str(response.status_code))
            if response.status_code == 429 or response.status_code >= 500:
                if attempt == _MAX_ATTEMPTS - 1:
                    if response.status_code == 429:
                        raise LangfuseRateLimited(f"HTTP {response.status_code}")
                    raise LangfuseServerError(f"HTTP {response.status_code}")
                header = response.headers.get("retry-after")
                await asyncio.sleep(self._delay(attempt, header))
                continue
            if response.status_code >= 400:
                raise LangfuseClientError(response.status_code, response.text[:500])
            return response
        raise LangfuseServerError(f"HTTP {last_status}")

    async def get_projects(self) -> list[dict[str, Any]]:
        response = await self._send("GET", "/api/public/projects", None)
        body = response.json()
        data = body.get("data") if isinstance(body, dict) else None
        if not isinstance(data, list):
            raise LangfuseClientError(response.status_code, "projects payload is not a list")
        return [item for item in data if isinstance(item, dict)]

    async def list_observations(self, params: list[tuple[str, str]]) -> ObservationsPage:
        response = await self._send("GET", "/api/public/v2/observations", params)
        body = response.json()
        data = body.get("data") if isinstance(body, dict) else None
        meta = body.get("meta") if isinstance(body, dict) else None
        rows = [item for item in data if isinstance(item, dict)] if isinstance(data, list) else []
        cursor = meta.get("cursor") if isinstance(meta, dict) else None
        if not isinstance(cursor, str) or cursor == "":
            cursor = None
        return ObservationsPage(data=rows, cursor=cursor)
