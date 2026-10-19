SELECT
  turn_id,
  trace_id,
  session_id,
  start_ts,
  end_ts,
  surface,
  depth_bucket,
  primary_response_model,
  prompt_version,
  turn_index,
  toUInt8(mixed_session) AS mixed_session,
  session_inferred,
  toUInt8(session_closed) AS session_closed,
  session_first_start,
  llm_errors,
  tool_calls,
  tool_errors,
  zero_tool_flag,
  loop_flag,
  format_ok,
  output_tokens,
  output_chars,
  latency_ms,
  cost_usd,
  late
FROM derived
WHERE release = {release:String}
  AND start_ts >= {ws:DateTime64(3)}
  AND start_ts < {we:DateTime64(3)}
  __ENV__
