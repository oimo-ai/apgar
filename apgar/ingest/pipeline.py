from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import replace
from datetime import datetime

from apgar.domain.models import SpanRow, TraceStateRow
from apgar.storage.interfaces import EventStore


async def _stored_spans(
    event_store: EventStore, keys: Sequence[tuple[str, str]]
) -> dict[tuple[str, str], list[SpanRow]]:
    if not keys:
        return {}
    # One read for every trace this batch already knows. A per-trace read sits on the OTLP path.
    batch = getattr(event_store, "spans_of_traces", None)
    if batch is not None:
        loaded: dict[tuple[str, str], list[SpanRow]] = await batch(list(keys))
        return loaded
    return {
        (source_id, trace_id): await event_store.spans_of_trace(source_id, trace_id)
        for source_id, trace_id in keys
    }


def _same_span(stored: SpanRow, incoming: SpanRow) -> bool:
    return replace(stored, ingested_at=incoming.ingested_at) == incoming


async def write_batch(event_store: EventStore, rows: Sequence[SpanRow], now: datetime) -> None:
    if not rows:
        return
    grouped: dict[tuple[str, str], list[SpanRow]] = defaultdict(list)
    for row in rows:
        grouped[(row.source_id, row.trace_id)].append(row)
    existing = await event_store.read_trace_state(list(grouped))
    stored_spans = await _stored_spans(
        event_store, [key for key in grouped if existing.get(key) is not None]
    )
    states: list[TraceStateRow] = []
    for key, group in grouped.items():
        source_id, trace_id = key
        previous = existing.get(key)
        has_root = any(span.parent_span_id == "" for span in group)
        if previous is None:
            states.append(
                TraceStateRow(
                    source_id=source_id,
                    trace_id=trace_id,
                    first_span_at=now,
                    last_span_at=now,
                    span_count=len(group),
                    has_root=has_root,
                    agent_id="",
                    root_span_id="",
                    release="",
                    start_ts=None,
                    assembled_at=None,
                    assembled_version=0,
                    content_hash="",
                    updated_at=now,
                )
            )
            continue
        known = {span.span_id: span for span in stored_spans.get(key, [])}
        fresh_ids: set[str] = set()
        changed = False
        for row in group:
            prior = known.get(row.span_id)
            if prior is None:
                fresh_ids.add(row.span_id)
                changed = True
            elif not _same_span(prior, row):
                changed = True
        # Identical lookback rows must leave last_span_at alone. Moving it would
        # hold the trace inside the quiet window. Changed content still moves it,
        # and the assembler skips a turn whose content_hash is unchanged.
        if not changed:
            continue
        states.append(
            TraceStateRow(
                source_id=source_id,
                trace_id=trace_id,
                first_span_at=previous.first_span_at,
                last_span_at=now,
                span_count=previous.span_count + len(fresh_ids),
                has_root=previous.has_root or has_root,
                agent_id=previous.agent_id,
                root_span_id=previous.root_span_id,
                release=previous.release,
                start_ts=previous.start_ts,
                assembled_at=previous.assembled_at,
                assembled_version=previous.assembled_version,
                content_hash=previous.content_hash,
                updated_at=now,
            )
        )
    await event_store.insert_spans(rows)
    await event_store.upsert_trace_state(states)
