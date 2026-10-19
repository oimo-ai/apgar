SELECT * FROM trace_state FINAL
WHERE ((has_root = 1 AND last_span_at <= {now:DateTime64(3)} - INTERVAL {quiet:UInt32} SECOND)
    OR first_span_at <= {now:DateTime64(3)} - INTERVAL {max_age:UInt32} SECOND)
  AND (assembled_at IS NULL OR assembled_at < last_span_at)
ORDER BY last_span_at
LIMIT {limit:UInt32}
