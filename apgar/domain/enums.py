from __future__ import annotations

from enum import StrEnum


class SpanKind(StrEnum):
    invoke_workflow = "invoke_workflow"
    invoke_agent = "invoke_agent"
    chat = "chat"
    execute_tool = "execute_tool"
    retrieval = "retrieval"
    other = "other"


class SpanStatus(StrEnum):
    ok = "ok"
    error = "error"
    unset = "unset"


class Source(StrEnum):
    otlp = "otlp"
    langfuse = "langfuse"


class VerdictState(StrEnum):
    PENDING = "PENDING"
    INCONCLUSIVE = "INCONCLUSIVE"
    PASS = "PASS"
    FAIL = "FAIL"


class ReasonCode(StrEnum):
    no_baseline = "no_baseline"
    insufficient_sample = "insufficient_sample"
    insufficient_baseline = "insufficient_baseline"
    insufficient_power = "insufficient_power"
    pass_candidate = "pass_candidate"
    fail_candidate = "fail_candidate"
    superseded = "superseded"
    window_elapsed = "window_elapsed"
    stopped = "stopped"
    confirmed = "confirmed"


class MetricStatus(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    INCONCLUSIVE = "INCONCLUSIVE"
    NA = "NA"
    EXPECTED = "EXPECTED"


class SliceStatus(StrEnum):
    FAIL = "FAIL"
    NOT_FLAGGED = "NOT_FLAGGED"
    INSUFFICIENT = "INSUFFICIENT"


class SliceDimension(StrEnum):
    tool = "tool"
    surface = "surface"
    session_depth = "session_depth"
    response_model = "response_model"
    prompt_version = "prompt_version"


class DepthBucket(StrEnum):
    short = "short"
    medium = "medium"
    long = "long"


class BaselineMode(StrEnum):
    manual = "manual"
    previous_release = "previous_release"


class Direction(StrEnum):
    up = "up"
    down = "down"
    both = "both"


class ToleranceMode(StrEnum):
    abs = "abs"
    rel = "rel"


class MetricRole(StrEnum):
    guardrail = "guardrail"
    informational = "informational"


class MetricLevel(StrEnum):
    turn = "turn"
    tool = "tool"
    session = "session"


class ReleaseEventType(StrEnum):
    manual_baseline = "manual_baseline"
    expected_changes = "expected_changes"
    stop = "stop"


class NotificationEvent(StrEnum):
    release_detected = "release_detected"
    regression = "regression"
    healthy = "healthy"
    ended = "ended"


class NotificationChannel(StrEnum):
    slack = "slack"
    webhook = "webhook"


class NotificationStatus(StrEnum):
    pending = "pending"
    sent = "sent"
    failed = "failed"


class ConnectionType(StrEnum):
    langfuse = "langfuse"
    slack = "slack"
    webhook = "webhook"


class ConnectionStatus(StrEnum):
    untested = "untested"
    ok = "ok"
    error = "error"


class JobRequestKind(StrEnum):
    evaluate = "evaluate"
    apply_events = "apply_events"
    demo_seed = "demo_seed"


class OutputFormat(StrEnum):
    text = "text"
    json = "json"


class MetricUnit(StrEnum):
    rate = "rate"
    count_ = "count"
    tokens = "tokens"
    chars = "chars"
    ms = "ms"
    usd = "usd"


class MetricId(StrEnum):
    tool_error_rate = "tool_error_rate"
    tool_retry_rate = "tool_retry_rate"
    loop_rate = "loop_rate"
    tool_calls_per_turn = "tool_calls_per_turn"
    zero_tool_turn_rate = "zero_tool_turn_rate"
    llm_error_rate = "llm_error_rate"
    format_failure_rate = "format_failure_rate"
    output_tokens_p50 = "output_tokens_p50"
    latency_p95 = "latency_p95"
    cost_per_turn = "cost_per_turn"
    turns_per_session = "turns_per_session"
