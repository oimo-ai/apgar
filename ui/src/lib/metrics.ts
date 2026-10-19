export const METRIC_IDS = [
  "tool_error_rate",
  "tool_retry_rate",
  "loop_rate",
  "tool_calls_per_turn",
  "zero_tool_turn_rate",
  "llm_error_rate",
  "format_failure_rate",
  "output_tokens_p50",
  "latency_p95",
  "cost_per_turn",
  "turns_per_session",
] as const;

export type MetricId = (typeof METRIC_IDS)[number];

export const METRIC_LABELS: Record<MetricId, string> = {
  tool_error_rate: "Tool error rate",
  tool_retry_rate: "Retry rate",
  loop_rate: "Loop rate",
  tool_calls_per_turn: "Tool calls per turn",
  zero_tool_turn_rate: "Turns without tools",
  llm_error_rate: "LLM error rate",
  format_failure_rate: "Format failure rate",
  output_tokens_p50: "Output length",
  latency_p95: "Latency p95",
  cost_per_turn: "Cost per turn",
  turns_per_session: "Turns per session",
};

export const METRIC_DESCRIPTIONS: Record<MetricId, string> = {
  tool_error_rate: "Share of tool calls that ended with an error.",
  tool_retry_rate: "Share of tool calls that repeat a failed call with the same tool and arguments in the same turn.",
  loop_rate: "Share of turns with three or more consecutive identical tool calls.",
  tool_calls_per_turn: "Average number of tool calls per turn. A drop usually means the agent stopped using its tools.",
  zero_tool_turn_rate: "Share of turns that finished without calling any tool.",
  llm_error_rate: "Share of turns where at least one LLM call failed.",
  format_failure_rate: "Share of turns whose final response is not valid JSON. Only for agents with JSON output.",
  output_tokens_p50: "Median output tokens per turn. Falls back to output characters when token counts are missing.",
  latency_p95: "95th percentile of turn latency.",
  cost_per_turn: "Average cost per turn, as reported on the chat spans.",
  turns_per_session: "Average number of turns in closed sessions.",
};

export function metricDescription(id: string): string | undefined {
  return METRIC_DESCRIPTIONS[id as MetricId];
}

export const METRIC_GROUPS: { id: string; title: string; ids: MetricId[] }[] = [
  {
    id: "behavior",
    title: "Behavior",
    ids: [
      "tool_calls_per_turn",
      "zero_tool_turn_rate",
      "tool_retry_rate",
      "loop_rate",
      "output_tokens_p50",
      "format_failure_rate",
      "turns_per_session",
    ],
  },
  { id: "reliability", title: "Reliability", ids: ["tool_error_rate", "llm_error_rate"] },
  { id: "cost_latency", title: "Cost and latency", ids: ["cost_per_turn", "latency_p95"] },
];

export const METRIC_ORDER: MetricId[] = METRIC_GROUPS.flatMap((group) => group.ids);

export function metricLabel(id: string): string {
  return METRIC_LABELS[id as MetricId] ?? id.replaceAll("_", " ");
}

export const SLICE_DIMENSION_LABELS: Record<string, string> = {
  tool: "Tool",
  surface: "Surface",
  session_depth: "Session depth",
  response_model: "Response model",
  prompt_version: "Prompt version",
};

export const SLICE_DIMENSIONS = [
  "tool",
  "surface",
  "session_depth",
  "response_model",
  "prompt_version",
] as const;

export const VERDICT_FIELDS = [
  "min_turns",
  "min_sessions",
  "min_turns_slice",
  "fail_confirmations",
  "pass_confirmations",
  "max_window_hours",
  "notify_healthy",
  "include_mixed_sessions",
  "alpha",
] as const;

// Matches min_trace_data_days() in apgar/domain/retention.py: 7 days of
// conversation history, 7 days of baseline, and 7 days of monitoring.
export const RETENTION_MIN_DAYS = 21;
export const RETENTION_MAX_DAYS = 3650;

export const RETENTION_FIELDS = [
  {
    name: "trace_data_days",
    label: "Trace Data",
    info: `Spans, turns, and tool calls received from your agents. Verdicts are computed from this data. Must be at least ${RETENTION_MIN_DAYS} days: Apgar compares a release with the week before it shipped, checks it for up to a week after, and looks one more week back to see where each conversation started.`,
  },
  {
    name: "verdict_history_days",
    label: "Verdict History",
    info: "Verdicts, metric tables, and notification records of each release. They stay after trace data is deleted, so older releases still show their result. Cannot be shorter than Trace Data. After this, a release keeps its label but loses its metric table.",
  },
] as const;

export const REASON_LABELS: Record<string, string> = {
  confirmed: "confirmed",
  fail_candidate: "fail candidate",
  pass_candidate: "pass candidate",
  insufficient_power: "insufficient power",
  insufficient_sample: "insufficient sample",
  insufficient_baseline: "insufficient baseline",
  no_baseline: "no baseline",
  superseded: "superseded",
  window_elapsed: "window elapsed",
  stopped: "stopped",
};

export const NA_REASONS: Record<string, string> = {
  disabled: "Disabled for this agent",
  no_tools: "No tool calls in one of the arms",
  no_content: "Message content not available",
  coverage: "Too few units carry the required input (below 90%)",
  zero_denominator: "No units in one of the arms",
  no_cost: "Cost not available for enough turns",
  no_sessions: "Not enough closed sessions or session ids missing",
};

export function reasonLabel(reason: string | null | undefined): string {
  if (!reason) {
    return "";
  }
  return REASON_LABELS[reason] ?? reason.replaceAll("_", " ");
}

export function naReasonLabel(reason: string | null | undefined): string {
  if (!reason) {
    return "n/a";
  }
  return NA_REASONS[reason] ?? reason;
}

const SLICE_REASONS: Record<string, string> = {
  unstable: "Too sparse for a stable comparison",
  zero_baseline: "Previous value is 0, so a relative change is undefined",
  not_applicable: "Not applicable",
};

export function sliceReasonLabel(reason: string | null | undefined): string {
  if (!reason) {
    return "Not enough data to compare";
  }
  return SLICE_REASONS[reason] ?? NA_REASONS[reason] ?? reason.replaceAll("_", " ");
}
