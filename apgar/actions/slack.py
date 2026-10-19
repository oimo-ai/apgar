from __future__ import annotations

from typing import Any

import httpx

from apgar.actions.errors import PermanentDeliveryError, RetryableDeliveryError


async def send_slack(http: httpx.AsyncClient, webhook_url: str, message: dict[str, Any]) -> None:
    try:
        response = await http.post(webhook_url, json=message)
    except httpx.HTTPError as exc:
        raise RetryableDeliveryError(str(exc)) from exc
    if response.status_code == 200:
        return
    if response.status_code == 429 or response.status_code >= 500:
        raise RetryableDeliveryError(f"HTTP {response.status_code}")
    raise PermanentDeliveryError(response.status_code, response.text[:500])
