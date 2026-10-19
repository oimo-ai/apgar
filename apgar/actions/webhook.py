from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime
from typing import Any

import httpx

from apgar import __version__
from apgar.actions.errors import PermanentDeliveryError, RetryableDeliveryError


def sign(secret: str, timestamp: int, body: bytes) -> str:
    message = f"{timestamp}.".encode() + body
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


async def send_webhook(
    http: httpx.AsyncClient,
    url: str,
    secret: str,
    payload: dict[str, Any],
    now: datetime,
) -> None:
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    timestamp = int(now.timestamp())
    headers = {
        "Content-Type": "application/json",
        "X-Apgar-Timestamp": str(timestamp),
        "X-Apgar-Signature": sign(secret, timestamp, body),
        "X-Apgar-Event": str(payload.get("event", "")),
        "User-Agent": f"apgar/{__version__}",
    }
    try:
        response = await http.post(url, content=body, headers=headers)
    except httpx.HTTPError as exc:
        raise RetryableDeliveryError(str(exc)) from exc
    if 200 <= response.status_code < 300:
        return
    if response.status_code == 429 or response.status_code >= 500:
        raise RetryableDeliveryError(f"HTTP {response.status_code}")
    raise PermanentDeliveryError(response.status_code, response.text[:500])
