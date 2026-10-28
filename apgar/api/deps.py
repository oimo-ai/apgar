from __future__ import annotations

import ipaddress
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from fastapi import Request

from apgar.api.errors import ApiError
from apgar.api.session import verify_session_cookie
from apgar.assembly.resolution import configured_attribute_keys
from apgar.config import Settings
from apgar.domain.models import IngestToken
from apgar.security import constant_time_equals, hash_token
from apgar.storage.interfaces import MetaStore

_LOG = logging.getLogger("apgar.api")
_TOKEN_TTL_SECONDS = 60
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


@dataclass(frozen=True, slots=True)
class Principal:
    kind: Literal["admin", "session"]


class IngestTokenCache:
    def __init__(self, meta_store: MetaStore, clock: Callable[[], datetime]) -> None:
        self._meta = meta_store
        self._clock = clock
        self._entries: dict[str, tuple[IngestToken | None, datetime]] = {}

    async def get(self, plaintext: str) -> IngestToken | None:
        digest = hash_token(plaintext)
        now = self._clock()
        cached = self._entries.get(digest)
        if cached is not None and (now - cached[1]).total_seconds() < _TOKEN_TTL_SECONDS:
            token = cached[0]
            if token is None or token.revoked_at is not None:
                return None
            return token
        try:
            fresh = await self._meta.get_ingest_token_by_hash(digest)
        except Exception as exc:
            raise ApiError("storage_unavailable", 503, "storage unavailable") from exc
        if fresh is not None and fresh.revoked_at is not None:
            fresh = None
        self._entries[digest] = (fresh, now)
        return fresh


class ConfiguredKeysCache:
    def __init__(self, meta_store: MetaStore, clock: Callable[[], datetime]) -> None:
        self._meta = meta_store
        self._clock = clock
        self._keys: frozenset[str] = frozenset()
        self._loaded_at: datetime | None = None

    async def get(self) -> frozenset[str]:
        now = self._clock()
        if (
            self._loaded_at is not None
            and (now - self._loaded_at).total_seconds() < _TOKEN_TTL_SECONDS
        ):
            return self._keys
        try:
            agents = await self._meta.list_agents()
        except Exception as exc:
            raise ApiError("storage_unavailable", 503, "storage unavailable") from exc
        self._keys = configured_attribute_keys(agents)
        self._loaded_at = now
        return self._keys

    def invalidate(self) -> None:
        self._loaded_at = None


def _bearer(request: Request) -> str | None:
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token.strip() or " " in token.strip():
        return None
    return token.strip()


def _cache(request: Request) -> IngestTokenCache:
    cached = getattr(request.app.state, "ingest_token_cache", None)
    if isinstance(cached, IngestTokenCache):
        return cached
    created = IngestTokenCache(request.app.state.meta_store, request.app.state.clock)
    request.app.state.ingest_token_cache = created
    return created


def configured_keys_cache(request: Request) -> ConfiguredKeysCache:
    cached = getattr(request.app.state, "configured_keys_cache", None)
    if isinstance(cached, ConfiguredKeysCache):
        return cached
    created = ConfiguredKeysCache(request.app.state.meta_store, request.app.state.clock)
    request.app.state.configured_keys_cache = created
    return created


async def require_ingest_token(request: Request) -> IngestToken:
    plaintext = _bearer(request)
    if plaintext is None:
        raise ApiError("unauthorized", 401, "unauthorized")
    token = await _cache(request).get(plaintext)
    if token is None:
        raise ApiError("unauthorized", 401, "unauthorized")
    return token


def _client_ip(request: Request) -> str:
    # Each proxy appends the address it received the request from, so only the last
    # `trusted_proxy_hops` entries are trustworthy. Earlier entries are whatever the
    # client sent.
    hops: int = request.app.state.settings.trusted_proxy_hops
    forwarded = [
        part.strip()
        for part in request.headers.get("x-forwarded-for", "").split(",")
        if part.strip()
    ]
    if hops > 0 and forwarded:
        address = forwarded[-min(hops, len(forwarded))]
        if len(forwarded) > hops:
            _warn_if_uncounted_proxy(request, address, hops, len(forwarded))
        return address
    client = request.client
    if client is None or not client.host:
        return "unknown"
    return client.host


def _warn_if_uncounted_proxy(request: Request, address: str, hops: int, entries: int) -> None:
    # A private address with more entries to its left is usually a reverse proxy in
    # front of the UI that APGAR_TRUSTED_PROXY_HOPS does not count. Every login would
    # then share that proxy's rate limit. A client that only adds entries of its own
    # leaves its public address here, so it does not trigger the warning.
    state = request.app.state
    if getattr(state, "uncounted_proxy_warned", False) or not _is_private(address):
        return
    state.uncounted_proxy_warned = True
    _LOG.warning(
        "x-forwarded-for has a private address where the client should be; "
        "count every proxy in front of apgar in APGAR_TRUSTED_PROXY_HOPS",
        extra={"trusted_proxy_hops": hops, "forwarded_entries": entries},
    )


def _is_private(address: str) -> bool:
    try:
        return ipaddress.ip_address(address).is_private
    except ValueError:
        return False


class LoginLimiter:
    def __init__(self) -> None:
        self._failures: dict[str, list[datetime]] = {}

    def blocked(self, ip: str, now: datetime) -> bool:
        recent = [
            stamp for stamp in self._failures.get(ip, []) if (now - stamp).total_seconds() < 60
        ]
        self._failures[ip] = recent
        return len(recent) >= 10

    def record_failure(self, ip: str, now: datetime) -> None:
        recent = [
            stamp for stamp in self._failures.get(ip, []) if (now - stamp).total_seconds() < 60
        ]
        recent.append(now)
        self._failures[ip] = recent


def login_limiter(request: Request) -> LoginLimiter:
    limiter = getattr(request.app.state, "login_limiter", None)
    if isinstance(limiter, LoginLimiter):
        return limiter
    created = LoginLimiter()
    request.app.state.login_limiter = created
    return created


async def authorize(request: Request) -> Principal:
    settings: Settings = request.app.state.settings
    bearer = _bearer(request)
    if bearer is not None:
        if constant_time_equals(bearer, settings.admin_token):
            return Principal("admin")
        raise ApiError("unauthorized", 401, "unauthorized")
    cookie = request.cookies.get("apgar_session")
    if cookie:
        now = request.app.state.clock()
        if not verify_session_cookie(cookie, settings.secret_key, now):
            raise ApiError("unauthorized", 401, "unauthorized")
        if request.method not in _SAFE_METHODS and request.headers.get("x-apgar-request") != "1":
            raise ApiError("forbidden", 403, "forbidden")
        return Principal("session")
    raise ApiError("unauthorized", 401, "unauthorized")
