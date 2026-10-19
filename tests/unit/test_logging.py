from __future__ import annotations

import json
import logging
import sys

from apgar.logging import JsonFormatter


def test_json_formatter_keys_and_extra_fields() -> None:
    formatter = JsonFormatter()
    record = logging.LogRecord(
        name="apgar.api",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="hello %s",
        args=("world",),
        exc_info=None,
    )
    record.agent = "billing-copilot"
    payload = json.loads(formatter.format(record))
    assert payload["level"] == "INFO"
    assert payload["logger"] == "apgar.api"
    assert payload["msg"] == "hello world"
    assert payload["agent"] == "billing-copilot"
    assert payload["ts"].endswith("Z")
    assert "pathname" not in payload

    try:
        raise RuntimeError("broken")
    except RuntimeError:
        failed = logging.LogRecord(
            name="apgar.worker",
            level=logging.ERROR,
            pathname=__file__,
            lineno=2,
            msg="job failed",
            args=(),
            exc_info=sys.exc_info(),
        )
    failed_payload = json.loads(formatter.format(failed))
    assert "RuntimeError: broken" in failed_payload["exc"]
