from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from apgar import __version__
from apgar.api.errors import (
    ApiError,
    CompactJSONResponse,
    error_response,
    status_code_for,
    validation_message,
)
from apgar.api.routes.agents import router as agents_router
from apgar.api.routes.auth import router as auth_router
from apgar.api.routes.connections import router as connections_router
from apgar.api.routes.demo import router as demo_router
from apgar.api.routes.ingest import router as ingest_router
from apgar.api.routes.notifications import router as notifications_router
from apgar.api.routes.ops import router as ops_router
from apgar.api.routes.releases import router as releases_router
from apgar.api.routes.settings import router as settings_router
from apgar.api.routes.tokens import router as tokens_router
from apgar.config import Settings
from apgar.domain.time import utcnow
from apgar.storage.interfaces import EventStore, MetaStore


def create_app(
    settings: Settings,
    event_store: EventStore,
    meta_store: MetaStore,
    clock: Callable[[], datetime] = utcnow,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        yield
        client = getattr(app.state, "client", None)
        close = getattr(client, "close", None)
        if close is not None:
            await close()

    app = FastAPI(
        title="Apgar",
        version=__version__,
        openapi_url="/api/openapi.json",
        docs_url=None,
        redoc_url=None,
        default_response_class=CompactJSONResponse,
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.event_store = event_store
    app.state.meta_store = meta_store
    app.state.clock = clock

    @app.exception_handler(ApiError)
    async def handle_api_error(_request: Request, exc: ApiError) -> CompactJSONResponse:
        return error_response(exc.status, exc.code, exc.message)

    @app.exception_handler(RequestValidationError)
    async def handle_validation(
        _request: Request, exc: RequestValidationError
    ) -> CompactJSONResponse:
        return error_response(422, "validation_error", validation_message(list(exc.errors())))

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_error(
        _request: Request, exc: StarletteHTTPException
    ) -> CompactJSONResponse:
        message = exc.detail if isinstance(exc.detail, str) else "request failed"
        return error_response(exc.status_code, status_code_for(exc.status_code), message)

    app.include_router(ops_router)
    app.include_router(ingest_router)
    app.include_router(auth_router)
    app.include_router(tokens_router)
    app.include_router(agents_router)
    app.include_router(connections_router)
    app.include_router(settings_router)
    app.include_router(releases_router)
    app.include_router(demo_router)
    app.include_router(notifications_router)
    return app
