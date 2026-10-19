from __future__ import annotations

import httpx
import respx

from apgar.actions.errors import PermanentDeliveryError, RetryableDeliveryError
from apgar.actions.slack import send_slack


async def test_slack_success_and_errors() -> None:
    async with httpx.AsyncClient() as http:
        with respx.mock:
            respx.post("https://hooks.slack.com/services/T/B/ok").mock(
                return_value=httpx.Response(200, text="ok")
            )
            await send_slack(http, "https://hooks.slack.com/services/T/B/ok", {"text": "hello"})
            respx.post("https://hooks.slack.com/services/T/B/slow").mock(
                return_value=httpx.Response(429, text="slow")
            )
            try:
                await send_slack(
                    http, "https://hooks.slack.com/services/T/B/slow", {"text": "hello"}
                )
            except RetryableDeliveryError:
                pass
            else:
                raise AssertionError("expected retry")
            respx.post("https://hooks.slack.com/services/T/B/gone").mock(
                return_value=httpx.Response(404, text="missing")
            )
            try:
                await send_slack(
                    http, "https://hooks.slack.com/services/T/B/gone", {"text": "hello"}
                )
            except PermanentDeliveryError as exc:
                assert exc.status == 404
            else:
                raise AssertionError("expected permanent")
