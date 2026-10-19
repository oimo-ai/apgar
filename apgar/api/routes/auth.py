from __future__ import annotations

from fastapi import APIRouter, Request, Response

from apgar.api.deps import _client_ip, authorize, login_limiter
from apgar.api.errors import ApiError
from apgar.api.schemas import LoginIn
from apgar.api.session import issue_session
from apgar.config import Settings
from apgar.security import constant_time_equals

router = APIRouter()


def _secure(request: Request, settings: Settings) -> bool:
    forwarded = request.headers.get("x-forwarded-proto") == "https"
    return forwarded or settings.cookie_secure


def _write_cookie(response: Response, request: Request, value: str, max_age: int) -> None:
    settings: Settings = request.app.state.settings
    response.set_cookie(
        "apgar_session",
        value,
        max_age=max_age,
        path="/",
        secure=_secure(request, settings),
        httponly=True,
        samesite="strict",
    )


@router.post("/api/v1/auth/login", status_code=204)
async def login(request: Request, body: LoginIn) -> Response:
    settings: Settings = request.app.state.settings
    now = request.app.state.clock()
    limiter = login_limiter(request)
    client_ip = _client_ip(request)
    if limiter.blocked(client_ip, now):
        raise ApiError("rate_limited", 429, "too many login attempts")
    if not constant_time_equals(body.token, settings.admin_token):
        limiter.record_failure(client_ip, now)
        raise ApiError("unauthorized", 401, "unauthorized")
    response = Response(status_code=204)
    _write_cookie(response, request, issue_session(settings.secret_key, now), 86400)
    return response


@router.post("/api/v1/auth/logout", status_code=204)
async def logout(request: Request) -> Response:
    response = Response(status_code=204)
    _write_cookie(response, request, "", 0)
    return response


@router.get("/api/v1/auth/session")
async def session(request: Request) -> dict[str, object]:
    principal = await authorize(request)
    return {"authenticated": True, "kind": principal.kind}
