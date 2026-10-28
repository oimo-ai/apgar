from __future__ import annotations

import asyncio
import ssl
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import clickhouse_connect
from clickhouse_connect.driver.exceptions import OperationalError

from apgar.config import Settings

INSERT_SETTINGS = {"async_insert": 1, "wait_for_async_insert": 1}
_SQL_DIR = Path(__file__).parent / "sql"


def _endpoint(url: str) -> tuple[str, int, bool]:
    parts = urlsplit(url)
    secure = parts.scheme == "https"
    host = parts.hostname or "localhost"
    port = parts.port if parts.port is not None else (8443 if secure else 8123)
    return host, port, secure


async def create_client(settings: Settings, database: str | None = None) -> Any:
    host, port, secure = _endpoint(settings.clickhouse_url)
    kwargs: dict[str, Any] = {
        "host": host,
        "port": port,
        "username": settings.clickhouse_user,
        "password": settings.clickhouse_password,
        "secure": secure,
        "verify": settings.clickhouse_verify,
    }
    if settings.clickhouse_ca_cert:
        kwargs["ca_cert"] = settings.clickhouse_ca_cert
    if database is not None:
        kwargs["database"] = database
    elif settings.clickhouse_database:
        kwargs["database"] = settings.clickhouse_database
    return await clickhouse_connect.get_async_client(**kwargs)


def is_unreachable(exc: BaseException) -> bool:
    """True when ClickHouse could not be reached at all, as while it is still starting."""
    if not isinstance(exc, OperationalError):
        return False
    # The driver raises a certificate that does not verify as a network error too. It is
    # a configuration error that waiting does not fix.
    cause = exc.__cause__
    while cause is not None:
        if isinstance(cause, ssl.SSLCertVerificationError):
            return False
        cause = cause.__cause__
    return True


async def ping(client: Any) -> bool:
    try:
        await asyncio.wait_for(client.query("SELECT 1"), timeout=2.0)
    except Exception:
        return False
    return True


@lru_cache(maxsize=32)
def load_sql(name: str) -> str:
    return (_SQL_DIR / f"{name}.sql").read_text(encoding="utf-8")
