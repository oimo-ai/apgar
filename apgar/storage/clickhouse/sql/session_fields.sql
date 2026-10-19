WITH scope_sessions AS (
  SELECT DISTINCT session_id FROM turns
  WHERE agent_id = {agent_id:String} AND (__SCOPE__)
),
base AS (
  SELECT * FROM turns FINAL
  WHERE agent_id = {agent_id:String}
    AND session_id IN (SELECT session_id FROM scope_sessions)
    AND start_ts >= {lookback_start:DateTime64(3)}
),
session_fields AS (
  SELECT
    *,
    row_number() OVER (PARTITION BY session_id ORDER BY start_ts, turn_id) AS turn_index,
    min(start_ts) OVER (PARTITION BY session_id) AS session_first_start,
    max(end_ts) OVER (PARTITION BY session_id) AS session_last_end,
    arrayExists(x -> x != release,
      groupUniqArray(release) OVER (PARTITION BY session_id ORDER BY start_ts, turn_id
                                    ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING)) AS mixed_session
  FROM base
),
derived AS (
  SELECT
    *,
    multiIf(turn_index <= 5, 'short', turn_index <= 20, 'medium', 'long') AS depth_bucket,
    session_last_end + INTERVAL 30 MINUTE < {now:DateTime64(3)} AS session_closed
  FROM session_fields
)
