import type { EvaluationOut, MetricItem, ReleaseDetail, VerdictSettings, VerdictSummary as Doc } from "@/api/types";
import { confirmationsSoFar, formatDuration, formatUntil, verdictSummary } from "@/lib/verdictSummary";

const NOW = Date.parse("2026-10-08T10:00:00Z");
const HEADLINE = "Tool error rate rose from 1.8% to 9.1% (allowed: up to +2 pp). Concentrated in tools sql_query.";

const settings: VerdictSettings = {
  min_turns: 200,
  min_sessions: 30,
  min_turns_slice: 50,
  fail_confirmations: 2,
  pass_confirmations: 2,
  max_window_hours: 72,
  notify_healthy: true,
  include_mixed_sessions: false,
  alpha: 0.05,
};

function metric(patch: Partial<MetricItem>): MetricItem {
  return {
    level: "turn",
    role: "guardrail",
    direction: "up",
    tolerance_mode: "abs",
    tolerance: 0.02,
    unit: "rate",
    applicable: true,
    na_reason: null,
    coverage: null,
    baseline: 0.018,
    candidate: 0.091,
    delta: 0.073,
    ci: [0.058, 0.089],
    status: "FAIL",
    turns_needed: 400,
    detectable_degradation: 0.029,
    n_candidate_units: 1842,
    n_baseline_units: 2210,
    trend: "flat",
    ...patch,
  };
}

function evaluation(patch: Partial<EvaluationOut> = {}): EvaluationOut {
  return {
    evaluated_at: "2026-10-08T10:00:00Z",
    manual: false,
    seed: 1,
    baseline_release: "9f8e7d6",
    baseline_mode: "previous_release",
    baseline_unverified: false,
    window_start: null,
    window_end: null,
    n_candidate_turns: 1842,
    n_baseline_turns: 2210,
    n_candidate_sessions: 300,
    n_baseline_sessions: 320,
    n_excluded_mixed: 0,
    n_excluded_untagged: 0,
    n_excluded_late: 0,
    state: "FAIL",
    reason: "confirmed",
    final: false,
    metrics: {
      items: { tool_error_rate: metric({}) },
      headline_metric: "tool_error_rate",
      sample: { turns_needed: null },
    },
    slices: {
      tool_error_rate: {
        tool: {
          applicable: true,
          values: [
            { value: "web_search", candidate: 0.05, baseline: 0.02, delta: 0.03, ci: null, p_value: null, p_adjusted: null, status: "FAIL", n_candidate: 1, n_baseline: 1 },
            { value: "sql_query", candidate: 0.2, baseline: 0.02, delta: 0.18, ci: null, p_value: null, p_adjusted: null, status: "FAIL", n_candidate: 1, n_baseline: 1 },
          ],
        },
        session_depth: {
          applicable: true,
          values: [
            { value: "long", candidate: 0.5, baseline: 0.02, delta: 0.48, ci: null, p_value: null, p_adjusted: null, status: "FAIL", n_candidate: 1, n_baseline: 1 },
          ],
        },
      },
    },
    duration_ms: 100,
    ...patch,
  } as EvaluationOut;
}

function doc(patch: Partial<Doc> = {}): Doc {
  return {
    agent: "billing-copilot",
    release: "a1b2c3d",
    verdict: "FAIL",
    reason: "confirmed",
    final: false,
    ok: false,
    baseline: { release: "9f8e7d6", mode: "previous_release", unverified: false },
    sample: { candidate_turns: 1842, baseline_turns: 2210, candidate_sessions: 300, baseline_sessions: 320 },
    excluded: { mixed: 0, untagged: 0, late: 0 },
    window: { start: null, end: null, max_end: null },
    evaluated_at: "2026-10-08T10:00:00Z",
    early: false,
    ended: null,
    detectability: "Can currently detect a change of +2.9 pp or more in tool error rate.",
    failed_metrics: [
      {
        id: "tool_error_rate",
        baseline: 0.018,
        candidate: 0.091,
        delta: 0.073,
        ci: [0.058, 0.089],
        tolerance: 0.02,
        tolerance_mode: "abs",
        direction: "up",
        unit: "rate",
        worst_slice: { dimension: "tool", value: "sql_query" },
        headline: HEADLINE,
      },
    ],
    report_url: "",
    ...patch,
  };
}

function detail(patch: Partial<ReleaseDetail>): ReleaseDetail {
  return {
    agent: "billing-copilot",
    agent_is_demo: false,
    release: "a1b2c3d",
    first_seen: "2026-10-08T01:00:00Z",
    last_seen: "2026-10-08T10:00:00Z",
    turn_count: 1842,
    state: "FAIL",
    reason: "confirmed",
    final: false,
    final_at: null,
    early: false,
    failing_metrics: [],
    baseline: { release: "9f8e7d6", mode: "previous_release", unverified: false },
    verdict_updated_at: null,
    max_window_end: "2026-10-11T01:00:00Z",
    user_state: { expected_changes: [], manual_baseline: null, changed_at: null, stopped_at: null },
    timing: { since_first_seen_seconds: 0, until_max_window_seconds: 0, last_check_at: null, next_check_at: null },
    evaluation: evaluation(),
    summary: doc(),
    coverage: null,
    actions: {
      baseline: { enabled: true },
      stop: { enabled: true },
      expected_changes: { enabled: true },
    },
    ...patch,
  };
}

const calm = { summary: doc({ failed_metrics: [] }) };

describe("verdictSummary", () => {
  it("labels a regression without confirmations", () => {
    const summary = verdictSummary(detail({}), settings, []);
    expect(summary).toEqual({ tone: "fail", label: "Regression", confirmations: null, collecting: false });
  });

  it("counts the confirmations of an early possible regression", () => {
    const summary = verdictSummary(
      detail({
        state: "INCONCLUSIVE",
        reason: "fail_candidate",
        early: true,
        evaluation: evaluation({ n_candidate_turns: 38 }),
        timing: { since_first_seen_seconds: 0, until_max_window_seconds: 0, last_check_at: null, next_check_at: "2026-10-08T10:07:00Z" },
      }),
      settings,
      [evaluation({ reason: "fail_candidate" })],
    );
    expect(summary).toMatchObject({ tone: "warning", label: "Possible regression, early" });
    expect(summary.confirmations).toEqual({ done: 1, needed: 2 });
  });

  it("labels a healthy release", () => {
    const summary = verdictSummary(detail({ state: "PASS", ...calm }), settings, []);
    expect(summary).toMatchObject({ tone: "pass", label: "Healthy", confirmations: null });
  });

  it("labels a release that ended or was stopped", () => {
    const superseded = verdictSummary(
      detail({
        state: "INCONCLUSIVE",
        reason: "superseded",
        final: true,
        final_at: "2026-10-08T10:00:00Z",
        summary: doc({ failed_metrics: [], ended: { reason: "superseded", by: "v1.10.0" } }),
      }),
      settings,
      [],
    );
    expect(superseded).toMatchObject({ tone: "calm", label: "Unconfirmed", confirmations: null });
    const stopped = verdictSummary(
      detail({
        state: "INCONCLUSIVE",
        reason: "stopped",
        final: true,
        final_at: "2026-10-08T03:00:00Z",
        user_state: { expected_changes: [], manual_baseline: null, changed_at: null, stopped_at: "2026-10-08T03:00:00Z" },
        summary: doc({ failed_metrics: [], ended: { reason: "stopped", by: null } }),
      }),
      settings,
      [],
    );
    expect(stopped).toMatchObject({ tone: "calm", label: "Unconfirmed" });
  });

  it("shows the first release without a comparison", () => {
    const summary = verdictSummary(detail({ state: "PENDING", reason: "no_baseline", turn_count: 12, evaluation: evaluation() }), settings, []);
    expect(summary).toMatchObject({ label: "First release", collecting: false });
  });

  it("waits for the first check", () => {
    const summary = verdictSummary(detail({ state: "PENDING", reason: "insufficient_sample", evaluation: null }), settings, []);
    expect(summary.collecting).toBe(false);
  });

  it("collects candidate and baseline traffic", () => {
    const candidate = verdictSummary(
      detail({ state: "PENDING", reason: "insufficient_sample", ...calm, evaluation: evaluation({ n_candidate_turns: 47, n_candidate_sessions: 7 }) }),
      settings,
      [],
    );
    expect(candidate).toMatchObject({ tone: "neutral", label: "Collecting", collecting: true });
    const baseline = verdictSummary(
      detail({ state: "PENDING", reason: "insufficient_baseline", ...calm, evaluation: evaluation({ n_baseline_turns: 120 }) }),
      settings,
      [],
    );
    expect(baseline.collecting).toBe(true);
  });

  it("stays calm without enough power", () => {
    const summary = verdictSummary(
      detail({ state: "INCONCLUSIVE", reason: "insufficient_power", ...calm, evaluation: evaluation({ n_candidate_turns: 412 }) }),
      settings,
      [],
    );
    expect(summary).toMatchObject({ tone: "calm", label: "Not enough data", confirmations: null });
  });

  it("counts pass confirmations", () => {
    const summary = verdictSummary(detail({ state: "INCONCLUSIVE", reason: "pass_candidate", ...calm }), settings, [evaluation({ reason: "pass_candidate" })]);
    expect(summary.confirmations).toEqual({ done: 1, needed: 2 });
  });
});

describe("helpers", () => {
  it("counts only the newest consecutive run", () => {
    const rows = [evaluation({ reason: "fail_candidate" }), evaluation({ reason: "fail_candidate" }), evaluation({ reason: "insufficient_power" }), evaluation({ reason: "fail_candidate" })];
    expect(confirmationsSoFar(rows, "fail_candidate")).toBe(2);
  });

  it("restarts the run after a baseline or expected changes event", () => {
    const rows = [
      evaluation({ reason: "fail_candidate", evaluated_at: "2026-10-08T12:00:00Z" }),
      evaluation({ reason: "fail_candidate", evaluated_at: "2026-10-08T11:00:00Z" }),
      evaluation({ reason: "fail_candidate", evaluated_at: "2026-10-08T10:00:00Z", baseline_release: "older" }),
    ];
    expect(confirmationsSoFar(rows, "fail_candidate")).toBe(2);
    expect(confirmationsSoFar(rows, "fail_candidate", "2026-10-08T11:30:00Z")).toBe(1);
  });

  it("formats durations and countdowns", () => {
    expect(formatDuration(45 * 60)).toBe("45 min");
    expect(formatDuration(9 * 3600 + 600)).toBe("9 h");
    expect(formatUntil("2026-10-08T10:00:20Z", NOW)).toBe("in under a minute");
    expect(formatUntil(null, NOW)).toBeNull();
  });
});
