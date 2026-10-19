from __future__ import annotations

import json
from datetime import UTC, datetime

import httpx
import respx

from apgar.actions.webhook import send_webhook, sign

NOW = datetime(2026, 10, 8, 9, 30, tzinfo=UTC)


async def test_webhook_signature_and_classification() -> None:
    seen: dict[str, str] = {}

    def _capture(request: httpx.Request) -> httpx.Response:
        seen["signature"] = request.headers["X-Apgar-Signature"]
        seen["body"] = request.content.decode()
        seen["event"] = request.headers["X-Apgar-Event"]
        return httpx.Response(204)

    async with httpx.AsyncClient() as http:
        with respx.mock:
            respx.post("https://example.test/hook").mock(side_effect=_capture)
            await send_webhook(
                http,
                "https://example.test/hook",
                "0123456789abcdef",
                {"event": "pass", "n": 1},
                NOW,
            )
            payload = {"event": "pass"}
            respx.post("https://example.test/down").mock(return_value=httpx.Response(503))
            try:
                await send_webhook(
                    http, "https://example.test/down", "0123456789abcdef", payload, NOW
                )
            except Exception as exc:
                assert type(exc).__name__ == "RetryableDeliveryError"
            else:
                raise AssertionError("expected retry")
            respx.post("https://example.test/bad").mock(
                return_value=httpx.Response(400, text="skew")
            )
            try:
                await send_webhook(
                    http, "https://example.test/bad", "0123456789abcdef", payload, NOW
                )
            except Exception as exc:
                assert type(exc).__name__ == "PermanentDeliveryError"
            else:
                raise AssertionError("expected permanent")
    payload = json.loads(seen["body"])
    stamp = int(NOW.timestamp())
    assert seen["signature"] == sign("0123456789abcdef", stamp, seen["body"].encode())
    assert seen["event"] == "pass"
    assert payload["event"] == "pass"
