export interface MetricSettings {
  enabled: boolean;
  direction: "up" | "down" | "both";
  tolerance_mode: "abs" | "rel";
  tolerance: number;
  role: "guardrail" | "informational";
}

export interface VerdictSettings {
  min_turns: number;
  min_sessions: number;
  min_turns_slice: number;
  fail_confirmations: number;
  pass_confirmations: number;
  max_window_hours: number;
  notify_healthy: boolean;
  include_mixed_sessions: boolean;
  alpha: number;
  confirmation_gap_minutes?: number;
}

export interface AgentFilter {
  trace_name: string | null;
  tags: string[];
  metadata: Record<string, string>;
  environment: string | null;
}

export interface AgentSync {
  status: string;
  watermark: string | null;
  last_success_at: string | null;
  lag_seconds: number | null;
  last_error: string;
}

export interface FailingMetric {
  id: string;
  headline: string;
}

export interface LatestRelease {
  release: string;
  state: string;
  reason: string;
  final: boolean;
  first_seen: string;
  early: boolean;
  failing_metrics: FailingMetric[];
}

export interface MetricCoverageItem {
  id: string;
  group: string;
  active: boolean;
  missing: string | null;
  share: number | null;
}

export interface MetricCoverage {
  active: number;
  total: number;
  groups: Record<string, { active: number; total: number }>;
  metrics: MetricCoverageItem[];
}

export interface AgentOut {
  name: string;
  source: "otlp" | "langfuse";
  langfuse_connection: string | null;
  filter: AgentFilter | null;
  environment: string | null;
  release: { from: string | null };
  surface_mapping: { from: string | null };
  output_format: "text" | "json";
  slack_connection: string | null;
  metrics: Record<string, Partial<MetricSettings>>;
  verdict: VerdictSettings;
  id: string;
  is_demo: boolean;
  created_at: string;
  updated_at: string;
  effective_metrics: Record<string, MetricSettings>;
  effective_verdict: VerdictSettings;
  activity: {
    turns_24h: number;
    untagged_share_24h: number;
    environments_24h: string[];
    last_turn_at: string | null;
  };
  latest_release: LatestRelease | null;
  coverage: MetricCoverage | null;
  sync: AgentSync | null;
  warnings: string[];
}

export interface ReleaseOut {
  agent: string;
  agent_is_demo: boolean;
  release: string;
  first_seen: string;
  last_seen: string | null;
  turn_count: number;
  state: string;
  reason: string;
  final: boolean;
  final_at: string | null;
  early: boolean;
  failing_metrics: FailingMetric[];
  baseline: { release: string | null; mode: string | null; unverified: boolean };
  verdict_updated_at: string | null;
  max_window_end: string;
}

export interface MetricItem {
  level: string;
  role: string;
  direction: "up" | "down" | "both";
  tolerance_mode: "abs" | "rel";
  tolerance: number;
  unit: string;
  applicable: boolean;
  na_reason: string | null;
  coverage: unknown;
  baseline: number | null;
  candidate: number | null;
  delta: number | null;
  ci: [number, number] | null;
  status: string;
  turns_needed: number | null;
  detectable_degradation: number | null;
  n_candidate_units: number;
  n_baseline_units: number;
  trend: "worsening" | "improving" | "flat" | null;
}

export interface SliceValue {
  value: string;
  candidate: number | null;
  baseline: number | null;
  delta: number | null;
  ci: [number, number] | null;
  p_value: number | null;
  p_adjusted: number | null;
  status: string;
  n_candidate: number;
  n_baseline: number;
  reason?: string | null;
}

export interface SliceDimensionBlock {
  applicable: boolean;
  values: SliceValue[];
}

export interface EvaluationOut {
  evaluated_at: string;
  manual: boolean;
  seed: string;
  baseline_release: string | null;
  baseline_mode: string | null;
  baseline_unverified: boolean;
  window_start: string | null;
  window_end: string | null;
  n_candidate_turns: number;
  n_baseline_turns: number;
  n_candidate_sessions: number;
  n_baseline_sessions: number;
  n_excluded_mixed: number;
  n_excluded_untagged: number;
  n_excluded_late: number;
  state: string;
  reason: string;
  final: boolean;
  metrics: {
    items?: Record<string, MetricItem>;
    headline_metric?: string | null;
    sample?: { turns_needed: number | null };
    early?: boolean;
  };
  slices?: Record<string, Record<string, SliceDimensionBlock>>;
  duration_ms: number;
}

export interface ReleaseEventOut {
  ts: string;
  type: string;
  payload: Record<string, unknown>;
  actor: string | null;
}

export interface ReleaseDetail extends ReleaseOut {
  user_state: {
    expected_changes: string[];
    manual_baseline: string | null;
    changed_at: string | null;
    stopped_at: string | null;
  };
  timing: {
    since_first_seen_seconds: number;
    until_max_window_seconds: number;
    last_check_at: string | null;
    next_check_at: string | null;
  };
  evaluation: EvaluationOut | null;
  summary: VerdictSummary;
  coverage: MetricCoverage | null;
  actions: {
    baseline: { enabled: boolean };
    stop: { enabled: boolean };
    expected_changes: { enabled: boolean };
  };
}

export interface NotificationOut {
  id: string;
  agent: string;
  release: string;
  event: string;
  channel: string;
  status: "pending" | "sent" | "failed";
  attempts: number;
  next_attempt_at: string | null;
  last_error: string | null;
  created_at: string;
  updated_at: string;
}

export interface ConnectionOut {
  id: string;
  name: string;
  type: "langfuse" | "slack" | "webhook";
  status: "untested" | "ok" | "error";
  last_checked_at: string | null;
  last_error: string | null;
  created_at: string;
  updated_at: string;
  config: Record<string, unknown>;
}

export interface IngestTokenOut {
  id: string;
  name: string;
  token_prefix: string;
  agent: string | null;
  auto_create_agents: boolean;
  created_at: string;
  revoked_at: string | null;
  token?: string;
}

export interface RetentionSettings {
  trace_data_days: number;
  verdict_history_days: number;
}

export interface SettingsOut {
  retention: RetentionSettings;
  telemetry: {
    enabled: boolean;
    disabled_by_environment: boolean;
    endpoint: string;
    last_sent_date: string | null;
    payload_preview: {
      api_key: string;
      event: string;
      distinct_id: string;
      timestamp: string;
      properties: Record<string, string | number | boolean | null>;
    };
  };
  appearance: { default_theme: "system" | "light" | "dark" };
}

export interface StatusOut {
  version: string;
  storage: string;
  schema_version: number | null;
  worker_heartbeat_age_seconds: number | null;
  demo_agents: number;
  demo_seeding: boolean;
  public_url?: string;
}

export interface FailedMetric {
  id: string;
  baseline: number | null;
  candidate: number | null;
  delta: number | null;
  ci: [number, number] | null;
  tolerance: number | null;
  tolerance_mode: "abs" | "rel" | null;
  direction: "up" | "down" | "both" | null;
  unit: string | null;
  worst_slice: { dimension: string; value: string } | null;
  headline?: string;
}

export interface VerdictSummary {
  agent: string;
  release: string;
  verdict: string;
  reason: string;
  final: boolean;
  ok: boolean | null;
  baseline: { release: string | null; mode: string | null; unverified: boolean };
  sample: {
    candidate_turns: number;
    baseline_turns: number;
    candidate_sessions: number;
    baseline_sessions: number;
  };
  excluded: { mixed: number; untagged: number; late: number };
  window: { start: string | null; end: string | null; max_end: string | null };
  evaluated_at: string | null;
  early?: boolean;
  ended?: { reason: string; by: string | null } | null;
  detectability?: string | null;
  failed_metrics: FailedMetric[];
  report_url: string;
}

export interface Page<T> {
  items: T[];
  total: number;
}

export interface SessionOut {
  authenticated: boolean;
  kind: string;
}
