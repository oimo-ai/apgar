from __future__ import annotations

from datetime import datetime, timedelta

from apgar.domain.settings import BASELINE_DAYS, MAX_WINDOW_HOURS

TRACE_DATA_DAYS = "trace_data_days"
VERDICT_HISTORY_DAYS = "verdict_history_days"

# Turns of a session older than this are left out of turn_index and mixed_session.
SESSION_LOOKBACK_DAYS = 7
RETENTION_MAX_DAYS = 3650

RETENTION_DEFAULTS: dict[str, int] = {
    TRACE_DATA_DAYS: 90,
    VERDICT_HISTORY_DAYS: 400,
}

# Settings fields. trace_state is absent: its TTL is APGAR_LATE_SPAN_DAYS.
RETENTION_TTLS: tuple[tuple[str, str, str], ...] = (
    ("spans", "toDateTime(start_ts)", TRACE_DATA_DAYS),
    ("turns", "toDateTime(start_ts)", TRACE_DATA_DAYS),
    ("tool_calls", "toDateTime(turn_start_ts)", TRACE_DATA_DAYS),
    ("verdict_evaluations", "toDateTime(evaluated_at)", VERDICT_HISTORY_DAYS),
    ("notifications", "toDateTime(created_at)", VERDICT_HISTORY_DAYS),
)

# Server time of the write, not first_span_at: a writer that replays history
# stamps first_span_at days back, and those rows would expire on insert.
TRACE_STATE_TTL = ("trace_state", "written_at")


def _monitoring_days() -> int:
    return (MAX_WINDOW_HOURS + 23) // 24


def min_trace_data_days() -> int:
    """Session history, the baseline window, and the longest monitoring window."""
    return SESSION_LOOKBACK_DAYS + BASELINE_DAYS + _monitoring_days()


def trace_window_stored(first_seen: datetime, now: datetime, trace_days: int) -> bool:
    """True when the baseline lookback and the release window are still inside retention."""
    oldest = first_seen - timedelta(days=BASELINE_DAYS + SESSION_LOOKBACK_DAYS)
    return oldest >= now - timedelta(days=trace_days)


TRACE_EXPIRED = "trace data for this release has expired, so it cannot be evaluated again"


def _bounds_reason(key: str) -> str:
    monitored = _monitoring_days()
    if key == TRACE_DATA_DAYS:
        return (
            f"Verdicts use {BASELINE_DAYS} days before a release, "
            f"up to {monitored} days after it, "
            f"and {SESSION_LOOKBACK_DAYS} days of conversation history before that."
        )
    return (
        "Verdict history is what remains after trace data is deleted, "
        f"and a release is monitored for up to {monitored} days."
    )


def retention_value_error(key: str, value: object) -> str | None:
    minimum = min_trace_data_days()
    out_of_range = (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not minimum <= value <= RETENTION_MAX_DAYS
    )
    if out_of_range:
        return (
            f"retention.{key}: must be in [{minimum}, {RETENTION_MAX_DAYS}]. {_bounds_reason(key)}"
        )
    return None


def verdict_history_error(trace_days: int, verdict_days: int) -> str | None:
    if verdict_days < trace_days:
        return (
            "retention.verdict_history_days: must be at least "
            f"trace_data_days ({trace_days}). "
            "It is the record that remains after trace data is deleted."
        )
    return None
