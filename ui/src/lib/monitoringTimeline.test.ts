import type { EvaluationOut, ReleaseDetail, ReleaseEventOut } from "@/api/types";
import { buildTimeline, fitWidths, timeScale } from "@/lib/monitoringTimeline";

const NOW = Date.parse("2026-10-08T13:00:00Z");

function check(evaluated_at: string, state: string, reason: string, patch: Partial<EvaluationOut> = {}): EvaluationOut {
  return {
    evaluated_at,
    manual: false,
    seed: evaluated_at,
    state,
    reason,
    final: false,
    baseline_release: "v1",
    metrics: {},
    ...patch,
  } as unknown as EvaluationOut;
}

function span(from: number, to: number) {
  return { from, to };
}

function event(ts: string, type: string, payload: Record<string, unknown> = {}): ReleaseEventOut {
  return { ts, type, payload, actor: null } as ReleaseEventOut;
}

function detail(patch: Partial<ReleaseDetail> = {}): ReleaseDetail {
  return {
    first_seen: "2026-10-08T01:00:00Z",
    last_seen: "2026-10-08T12:00:00Z",
    state: "INCONCLUSIVE",
    reason: "pass_candidate",
    final: false,
    final_at: null,
    max_window_end: "2026-10-11T01:00:00Z",
    user_state: { expected_changes: [], manual_baseline: null, changed_at: null, stopped_at: null },
    timing: { last_check_at: "2026-10-08T12:30:00Z", next_check_at: "2026-10-08T13:15:00Z" },
    evaluation: { window_end: null },
    summary: null,
    ...patch,
  } as unknown as ReleaseDetail;
}

const ENDED = {
  state: "INCONCLUSIVE",
  reason: "superseded",
  final: true,
  final_at: "2026-10-08T12:00:00Z",
  evaluation: { window_end: "2026-10-08T12:00:00Z" },
  summary: { ended: { reason: "superseded", by: "v3" } },
} as unknown as Partial<ReleaseDetail>;

describe("buildTimeline", () => {
  it("runs consecutive checks with the same outcome into one segment", () => {
    const history = [
      check("2026-10-08T12:30:00Z", "INCONCLUSIVE", "pass_candidate"),
      check("2026-10-08T12:15:00Z", "INCONCLUSIVE", "insufficient_power", { manual: true }),
      check("2026-10-08T12:00:00Z", "INCONCLUSIVE", "insufficient_power"),
    ];
    const timeline = buildTimeline(detail(), history, [], NOW);
    expect(timeline.segments.map(({ kind, checks }) => [kind, checks])).toEqual([
      ["collecting", 0],
      ["not_enough_data", 2],
      ["looks_healthy", 1],
    ]);
    expect(timeline.segments[1].tip).toEqual({
      title: "Not enough data",
      meaning: "No regression, but small changes would not show yet.",
      facts: [
        { label: "Checks", value: "2, 1 manual" },
        { label: "From", value: "Oct 8, 12:00 UTC" },
        { label: "To", value: "Oct 8, 12:15 UTC" },
        { label: "Baseline", value: "v1", mono: true },
      ],
      notes: [],
    });
    expect(timeline.segments[2].tip.facts.slice(0, 2)).toEqual([
      { label: "Checks", value: "1" },
      { label: "At", value: "Oct 8, 12:30 UTC" },
    ]);
    expect(timeline.segments[2].to).toBe(NOW);
    expect(timeline.markers).toEqual([
      { kind: "now", at: NOW, tip: { title: "Now", facts: [{ label: "Next check", value: "in 15 min" }], notes: [] } },
    ]);
    expect(timeline.rest).toEqual({
      title: "Remaining window",
      meaning: "Monitoring runs until this time at the latest.",
      facts: [{ label: "Ends by", value: "Oct 11, 01:00 UTC" }],
      notes: [],
    });
  });

  it("splits a run when the baseline changes and dims what came before", () => {
    const history = [
      check("2026-10-08T12:30:00Z", "INCONCLUSIVE", "pass_candidate", { baseline_release: "v2", manual: true }),
      check("2026-10-08T12:00:00Z", "INCONCLUSIVE", "pass_candidate"),
    ];
    const timeline = buildTimeline(
      detail({ user_state: { expected_changes: [], manual_baseline: "v2", changed_at: "2026-10-08T12:20:00Z", stopped_at: null } }),
      history,
      [event("2026-10-08T12:20:00Z", "manual_baseline", { release: "v2" })],
      NOW,
    );
    expect(timeline.segments.slice(1).map(({ kind, stale }) => [kind, stale])).toEqual([
      ["looks_healthy", true],
      ["looks_healthy", false],
    ]);
    expect(timeline.segments[1].tip.notes).toEqual(["Before the last change, so it no longer counts toward confirmation."]);
    expect(timeline.segments[2].tip.facts[0]).toEqual({ label: "Checks", value: "1, manual" });
    expect(timeline.markers[0]).toEqual({
      kind: "baseline",
      at: Date.parse("2026-10-08T12:20:00Z"),
      tip: {
        title: "Baseline changed",
        facts: [
          { label: "To", value: "v2", mono: true },
          { label: "Before", value: "v1", mono: true },
          { label: "When", value: "Oct 8, 12:20 UTC" },
        ],
        notes: ["Confirmation started over."],
      },
    });
  });

  it("records a stop request and drops an unknown event", () => {
    const timeline = buildTimeline(
      detail(),
      [],
      [event("2026-10-08T12:20:00Z", "stop"), event("2026-10-08T12:21:00Z", "note")],
      NOW,
    );
    expect(timeline.markers[0]).toMatchObject({ kind: "stop", tip: { title: "Stop requested" } });
    expect(timeline.markers.some((marker) => marker.kind === "stop")).toBe(true);
  });

  it("names expected changes by metric", () => {
    const timeline = buildTimeline(detail(), [], [event("2026-10-08T12:20:00Z", "expected_changes", { metrics: [] })], NOW);
    expect(timeline.markers[0]).toMatchObject({ kind: "expected", tip: { title: "Expected changes updated" } });
    expect(timeline.markers[0].tip.facts[0]).toEqual({ label: "Metrics", value: "None" });
  });

  it("ends with a flag that says who took over and the final verdict", () => {
    const history = [check("2026-10-08T11:00:00Z", "INCONCLUSIVE", "superseded", { final: true })];
    const timeline = buildTimeline(detail(ENDED), history, [event("2026-10-08T12:30:00Z", "manual_baseline", { release: "v0" })], NOW);
    const end = Date.parse("2026-10-08T12:00:00Z");
    expect(timeline.end).toBe(end);
    expect(timeline.live).toBe(false);
    expect(timeline.segments.at(-1)).toMatchObject({ kind: "unconfirmed", to: end, stale: false });
    expect(timeline.markers.map(({ kind, at }) => [kind, at])).toEqual([
      ["baseline", end],
      ["end", end],
    ]);
    expect(timeline.markers[0].tip.notes).toEqual(["After monitoring ended."]);
    expect(timeline.markers[1].tip).toEqual({
      title: "Replaced by v3",
      facts: [
        { label: "Ended", value: "Oct 8, 12:00 UTC" },
        { label: "Verdict", value: "Unconfirmed" },
      ],
      notes: [],
    });
    expect(timeline.rest?.title).toBe("Not monitored");
  });

  it("leaves out the stop request when the stop is what ended monitoring", () => {
    const stopped = {
      ...ENDED,
      reason: "stopped",
      summary: { ended: { reason: "stopped", by: null } },
    } as unknown as Partial<ReleaseDetail>;
    const timeline = buildTimeline(detail(stopped), [], [event("2026-10-08T11:59:00Z", "stop")], NOW);
    expect(timeline.markers.map(({ kind, tip }) => [kind, tip.title])).toEqual([["end", "Monitoring stopped"]]);
  });

  it("explains a long gap without checks", () => {
    const history = [
      check("2026-10-08T12:00:00Z", "INCONCLUSIVE", "pass_candidate"),
      check("2026-10-08T02:00:00Z", "PENDING", "insufficient_sample"),
    ];
    const timeline = buildTimeline(detail(), history, [], NOW);
    expect(timeline.segments[1].tip.notes).toEqual(["No checks for 10 h after this. Checks pause when no new turns arrive."]);
  });

  it("flags a release that has had no traffic for a day", () => {
    const timeline = buildTimeline(detail({ last_seen: "2026-10-07T12:00:00Z" }), [], [], NOW);
    expect(timeline.idle).toBe(true);
    expect(timeline.markers[0].tip).toEqual({ title: "Now", facts: [], notes: ["No traffic for over 24 h, so checks are paused."] });
  });
});

describe("fitWidths", () => {
  it("keeps proportions when every span is wide enough", () => {
    expect(fitWidths([span(0, 50), span(50, 100)], 200, 10)).toEqual([100, 100]);
  });

  it("gives short spans the minimum and takes the room from the long ones in proportion", () => {
    const widths = fitWidths([span(0, 1), span(1, 61), span(61, 61), span(61, 181)], 300, 10);
    expect(widths[0]).toBe(10);
    expect(widths[2]).toBe(10);
    expect(widths[3] / widths[1]).toBeCloseTo(2);
    expect(widths.reduce((sum, width) => sum + width, 0)).toBeCloseTo(300);
  });

  it("splits the width evenly when the minimum does not fit", () => {
    expect(fitWidths([span(0, 1), span(1, 2), span(2, 100)], 15, 10)).toEqual([5, 5, 5]);
  });
});

describe("timeScale", () => {
  it("maps times inside each box and puts a time at a zero length box after it", () => {
    const { boxes, at } = timeScale([span(0, 100), span(100, 100), span(100, 200)], 210, 10);
    expect(boxes.map(({ x, width }) => [x, width])).toEqual([
      [0, 100],
      [100, 10],
      [110, 100],
    ]);
    expect(at(50)).toBe(50);
    expect(at(100)).toBe(110);
    expect(at(150)).toBe(160);
    expect(at(200)).toBe(210);
    expect(at(-1)).toBe(0);
  });
});
