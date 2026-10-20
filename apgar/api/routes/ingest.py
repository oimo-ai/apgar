from __future__ import annotations

import logging

from fastapi import APIRouter, Request
from fastapi.responses import Response
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceResponse

from apgar.api.deps import configured_keys_cache, require_ingest_token
from apgar.api.errors import ApiError, CompactJSONResponse, error_response
from apgar.api.metrics import (
    INGEST_BYTES,
    INGEST_REQUESTS,
    INGEST_SPANS_ACCEPTED,
    INGEST_SPANS_DROPPED,
    INGEST_SPANS_RECEIVED,
    INGEST_STORAGE_ERRORS,
)
from apgar.domain.enums import Source
from apgar.ingest.pipeline import write_batch
from apgar.normalize.normalizer import HmacKeys, MalformedSpan, normalize
from apgar.normalize.otlp import (
    MalformedPayload,
    PayloadTooLarge,
    UnsupportedMediaType,
    decode_request,
    iter_raw_spans,
)

_LOG = logging.getLogger("apgar.ingest")
router = APIRouter()


def _media(content_type: str) -> str:
    return content_type.split(";", 1)[0].strip().lower()


async def _read_limited(request: Request) -> bytes:
    limit = int(request.app.state.settings.max_body_bytes)
    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > limit:
            raise ApiError("payload_too_large", 413, "request body exceeds limit")
        chunks.append(chunk)
    return b"".join(chunks)


@router.post("/v1/traces")
async def ingest_traces(request: Request) -> Response:
    source_id = "unknown"
    status_label = "500"
    body = b""
    try:
        body = await _read_limited(request)
        token = await require_ingest_token(request)
        source_id = token.id
        content_type = request.headers.get("content-type", "")
        try:
            decoded = decode_request(
                body,
                content_type,
                request.headers.get("content-encoding"),
                max_body_bytes=request.app.state.settings.max_body_bytes,
            )
        except PayloadTooLarge:
            status_label = "413"
            raise ApiError("payload_too_large", 413, "request body exceeds limit") from None
        except UnsupportedMediaType:
            status_label = "415"
            raise ApiError("unsupported_media_type", 415, "unsupported media type") from None
        except MalformedPayload as exc:
            status_label = "400"
            raise ApiError("malformed_payload", 400, str(exc)) from None
        settings = request.app.state.settings
        now = request.app.state.clock()
        keys = HmacKeys.from_settings(settings)
        configured = await configured_keys_cache(request).get()
        raw_spans = list(iter_raw_spans(decoded))
        INGEST_SPANS_RECEIVED.labels(source_id=source_id).inc(len(raw_spans))
        rows = []
        dropped_ids = 0
        dropped_timestamps = 0
        for raw in raw_spans:
            if raw.trace_id == "":
                dropped_ids += 1
                continue
            try:
                rows.append(
                    normalize(
                        raw,
                        source_id=token.id,
                        source=Source.otlp,
                        agent_hint=token.agent_id,
                        now=now,
                        late_days=settings.late_span_days,
                        keys=keys,
                        configured=configured,
                    )
                )
            except MalformedSpan:
                dropped_timestamps += 1
        if dropped_ids:
            INGEST_SPANS_DROPPED.labels(source_id=source_id, reason="invalid_ids").inc(dropped_ids)
        if dropped_timestamps:
            INGEST_SPANS_DROPPED.labels(source_id=source_id, reason="invalid_timestamps").inc(
                dropped_timestamps
            )
        try:
            await write_batch(request.app.state.event_store, rows, now)
        except Exception:
            status_label = "503"
            INGEST_STORAGE_ERRORS.inc()
            _LOG.exception("ingest storage failure", extra={"source_id": source_id})
            response = error_response(503, "storage_unavailable", "storage unavailable")
            response.headers["Retry-After"] = "5"
            return response
        INGEST_SPANS_ACCEPTED.labels(source_id=source_id).inc(len(rows))
        status_label = "200"
        if _media(content_type) == "application/x-protobuf":
            payload = ExportTraceServiceResponse().SerializeToString()
            return Response(content=payload, media_type="application/x-protobuf")
        return CompactJSONResponse({})
    except ApiError as exc:
        if exc.status == 503:
            status_label = "503"
            INGEST_STORAGE_ERRORS.inc()
            response = error_response(503, exc.code, exc.message)
            response.headers["Retry-After"] = "5"
            return response
        if status_label == "500":
            status_label = str(exc.status)
        raise
    finally:
        INGEST_BYTES.labels(source_id=source_id).inc(len(body))
        INGEST_REQUESTS.labels(source_id=source_id, status=status_label).inc()
