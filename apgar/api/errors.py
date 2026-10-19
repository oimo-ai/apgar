from __future__ import annotations

import json
from typing import Any

from fastapi.responses import JSONResponse


class ApiError(Exception):
    def __init__(self, code: str, status: int, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.status = status
        self.message = message


class CompactJSONResponse(JSONResponse):
    def render(self, content: Any) -> bytes:
        return json.dumps(content, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


_STATUS_CODES = {
    400: "not_allowed",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    409: "conflict",
    413: "payload_too_large",
    422: "validation_error",
    429: "rate_limited",
    503: "storage_unavailable",
    504: "timeout",
}


def error_response(status: int, code: str, message: str) -> CompactJSONResponse:
    return CompactJSONResponse(
        status_code=status,
        content={"error": {"code": code, "message": message}},
    )


def status_code_for(status: int) -> str:
    return _STATUS_CODES.get(status, "error")


def validation_message(errors: list[dict[str, Any]]) -> str:
    if not errors:
        return "validation failed"
    first = errors[0]
    loc = ".".join(str(part) for part in first.get("loc", ()))
    message = str(first.get("msg", "validation failed"))
    if loc:
        return f"{loc}: {message}"
    return message
