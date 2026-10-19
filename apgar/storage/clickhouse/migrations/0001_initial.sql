CREATE TABLE IF NOT EXISTS schema_migrations (
  version UInt32,
  name String,
  applied_at DateTime64(3, 'UTC') DEFAULT now64(3)
) ENGINE = MergeTree ORDER BY (version)
;
CREATE TABLE IF NOT EXISTS spans (
  source_id String,
  trace_id String,
  span_id String,
  parent_span_id String,
  kind LowCardinality(String),
  name String,
  start_ts DateTime64(3, 'UTC'),
  end_ts DateTime64(3, 'UTC'),
  status LowCardinality(String),
  error_type String,
  agent_hint String,
  attributes Map(String, String),
  request_model LowCardinality(String),
  response_model LowCardinality(String),
  input_tokens Nullable(UInt64),
  output_tokens Nullable(UInt64),
  cost_usd Nullable(Float64),
  tool_name LowCardinality(String),
  tool_call_id String,
  args_hash String,
  output_chars Nullable(UInt32),
  output_json_valid Nullable(UInt8),
  late UInt8,
  ingested_at DateTime64(3, 'UTC')
) ENGINE = ReplacingMergeTree(ingested_at)
PARTITION BY toYYYYMM(start_ts)
ORDER BY (source_id, trace_id, span_id)
TTL toDateTime(start_ts) + INTERVAL 90 DAY
;
CREATE TABLE IF NOT EXISTS trace_state (
  source_id String,
  trace_id String,
  first_span_at DateTime64(3, 'UTC'),
  last_span_at DateTime64(3, 'UTC'),
  span_count UInt32,
  has_root UInt8,
  agent_id String,
  root_span_id String,
  release String,
  start_ts Nullable(DateTime64(3, 'UTC')),
  assembled_at Nullable(DateTime64(3, 'UTC')),
  assembled_version UInt32,
  content_hash String,
  updated_at DateTime64(6, 'UTC'),
  written_at DateTime('UTC') DEFAULT now(),
  INDEX idx_last_span_at last_span_at TYPE minmax GRANULARITY 1
) ENGINE = ReplacingMergeTree(updated_at)
ORDER BY (source_id, trace_id)
TTL written_at + INTERVAL 7 DAY
;
CREATE TABLE IF NOT EXISTS turns (
  agent_id String,
  release String,
  start_ts DateTime64(3, 'UTC'),
  turn_id String,
  trace_id String,
  root_span_id String,
  source_id String,
  environment LowCardinality(String),
  prompt_version String,
  session_id String,
  session_inferred UInt8,
  surface LowCardinality(String),
  end_ts DateTime64(3, 'UTC'),
  latency_ms UInt32,
  llm_calls UInt16,
  llm_errors UInt16,
  tool_calls UInt16,
  tool_errors UInt16,
  tool_retries Nullable(UInt16),
  loop_flag Nullable(UInt8),
  zero_tool_flag UInt8,
  input_tokens Nullable(UInt64),
  output_tokens Nullable(UInt64),
  output_chars Nullable(UInt32),
  cost_usd Nullable(Float64),
  primary_response_model LowCardinality(String),
  response_models Array(String),
  format_ok Nullable(UInt8),
  late UInt8,
  partial UInt8,
  source LowCardinality(String),
  ingested_at DateTime64(3, 'UTC'),
  version UInt32,
  INDEX idx_trace_id trace_id TYPE bloom_filter(0.01) GRANULARITY 4,
  INDEX idx_session_id session_id TYPE bloom_filter(0.01) GRANULARITY 4,
  INDEX idx_ingested_at ingested_at TYPE minmax GRANULARITY 1
) ENGINE = ReplacingMergeTree(version)
PARTITION BY toYYYYMM(start_ts)
ORDER BY (agent_id, release, start_ts, turn_id)
TTL toDateTime(start_ts) + INTERVAL 90 DAY
;
CREATE TABLE IF NOT EXISTS tool_calls (
  agent_id String,
  release String,
  turn_start_ts DateTime64(3, 'UTC'),
  turn_id String,
  tool_call_id String,
  session_id String,
  tool_name LowCardinality(String),
  call_start_ts DateTime64(3, 'UTC'),
  duration_ms UInt32,
  status LowCardinality(String),
  error_type String,
  args_hash String,
  is_retry Nullable(UInt8),
  surface LowCardinality(String),
  version UInt32
) ENGINE = ReplacingMergeTree(version)
PARTITION BY toYYYYMM(turn_start_ts)
ORDER BY (agent_id, release, turn_start_ts, turn_id, tool_call_id)
TTL toDateTime(turn_start_ts) + INTERVAL 90 DAY
;
CREATE TABLE IF NOT EXISTS agents (
  id String,
  name String,
  source LowCardinality(String),
  langfuse_connection_id String,
  filter String,
  environment String,
  surface_mapping String,
  release_settings String,
  metric_settings String,
  verdict_settings String,
  output_format LowCardinality(String),
  slack_connection_id String,
  is_demo UInt8,
  created_at DateTime64(3, 'UTC'),
  updated_at DateTime64(6, 'UTC'),
  deleted_at Nullable(DateTime64(3, 'UTC')),
  is_deleted UInt8
) ENGINE = ReplacingMergeTree(updated_at, is_deleted)
ORDER BY (id)
;
CREATE TABLE IF NOT EXISTS connections (
  id String,
  name String,
  type LowCardinality(String),
  config_encrypted String,
  status LowCardinality(String),
  last_checked_at Nullable(DateTime64(3, 'UTC')),
  last_error String,
  created_at DateTime64(3, 'UTC'),
  updated_at DateTime64(6, 'UTC'),
  is_deleted UInt8
) ENGINE = ReplacingMergeTree(updated_at, is_deleted)
ORDER BY (id)
;
CREATE TABLE IF NOT EXISTS ingest_tokens (
  id String,
  name String,
  token_hash String,
  token_prefix String,
  agent_id String,
  auto_create_agents UInt8,
  created_at DateTime64(3, 'UTC'),
  revoked_at Nullable(DateTime64(3, 'UTC')),
  updated_at DateTime64(6, 'UTC'),
  is_deleted UInt8
) ENGINE = ReplacingMergeTree(updated_at, is_deleted)
ORDER BY (id)
;
CREATE TABLE IF NOT EXISTS settings (
  key String,
  value String,
  updated_at DateTime64(6, 'UTC'),
  is_deleted UInt8
) ENGINE = ReplacingMergeTree(updated_at, is_deleted)
ORDER BY (key)
;
CREATE TABLE IF NOT EXISTS sync_state (
  connection_id String,
  watermark Nullable(DateTime64(3, 'UTC')),
  last_success_at Nullable(DateTime64(3, 'UTC')),
  last_error String,
  last_error_at Nullable(DateTime64(3, 'UTC')),
  lag_seconds Nullable(Int64),
  in_progress UInt8,
  updated_at DateTime64(6, 'UTC'),
  is_deleted UInt8
) ENGINE = ReplacingMergeTree(updated_at, is_deleted)
ORDER BY (connection_id)
;
CREATE TABLE IF NOT EXISTS releases (
  agent_id String,
  release String,
  first_seen DateTime64(3, 'UTC'),
  state LowCardinality(String),
  reason LowCardinality(String),
  final UInt8,
  final_at Nullable(DateTime64(3, 'UTC')),
  selected_baseline_release String,
  selected_baseline_mode LowCardinality(String),
  baseline_unverified UInt8,
  verdict_summary String,
  verdict_updated_at Nullable(DateTime64(3, 'UTC')),
  last_seen Nullable(DateTime64(3, 'UTC')),
  turn_count UInt64,
  updated_at DateTime64(6, 'UTC')
) ENGINE = ReplacingMergeTree(updated_at)
ORDER BY (agent_id, release)
;
CREATE TABLE IF NOT EXISTS release_events (
  agent_id String,
  release String,
  ts DateTime64(3, 'UTC'),
  type LowCardinality(String),
  payload String,
  actor String
) ENGINE = MergeTree
ORDER BY (agent_id, release, ts)
;
CREATE TABLE IF NOT EXISTS verdict_evaluations (
  agent_id String,
  release String,
  evaluated_at DateTime64(3, 'UTC'),
  manual UInt8,
  seed String,
  baseline_release String,
  baseline_mode LowCardinality(String),
  baseline_unverified UInt8,
  window_start Nullable(DateTime64(3, 'UTC')),
  window_end Nullable(DateTime64(3, 'UTC')),
  n_candidate_turns UInt64,
  n_baseline_turns UInt64,
  n_candidate_sessions UInt64,
  n_baseline_sessions UInt64,
  n_excluded_mixed UInt64,
  n_excluded_untagged UInt64,
  n_excluded_late UInt64,
  state LowCardinality(String),
  reason LowCardinality(String),
  final UInt8,
  metrics String,
  slices String,
  duration_ms UInt32
) ENGINE = MergeTree
ORDER BY (agent_id, release, evaluated_at)
TTL toDateTime(evaluated_at) + INTERVAL 400 DAY
;
CREATE TABLE IF NOT EXISTS notifications (
  id String,
  agent_id String,
  release String,
  event LowCardinality(String),
  idempotency_key String,
  channel LowCardinality(String),
  connection_id String,
  status LowCardinality(String),
  attempts UInt8,
  next_attempt_at DateTime64(3, 'UTC'),
  last_error String,
  payload String,
  created_at DateTime64(3, 'UTC'),
  updated_at DateTime64(6, 'UTC')
) ENGINE = ReplacingMergeTree(updated_at)
ORDER BY (idempotency_key, channel)
TTL toDateTime(created_at) + INTERVAL 400 DAY
;
CREATE TABLE IF NOT EXISTS job_requests (
  id String,
  agent_id String,
  release String,
  kind LowCardinality(String),
  payload String,
  requested_at DateTime64(3, 'UTC'),
  processed_at Nullable(DateTime64(3, 'UTC')),
  updated_at DateTime64(6, 'UTC')
) ENGINE = ReplacingMergeTree(updated_at)
ORDER BY (agent_id, release, id)
TTL toDateTime(requested_at) + INTERVAL 7 DAY
;
