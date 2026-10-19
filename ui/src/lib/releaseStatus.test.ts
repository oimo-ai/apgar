import type { ReleaseDetail } from "@/api/types";
import { releaseStatus } from "@/lib/releaseStatus";

function detail(patch: Record<string, unknown> = {}): ReleaseDetail {
  return {
    agent: "billing-copilot",
    release: "a1b2c3d",
    state: "INCONCLUSIVE",
    reason: "insufficient_power",
    final: false,
    early: false,
    user_state: { expected_changes: [], manual_baseline: null, changed_at: null, stopped_at: null },
    evaluation: { n_candidate_turns: 38 },
    summary: null,
    ...patch,
  } as unknown as ReleaseDetail;
}

const stopped = { stopped_at: "2026-10-08T03:00:00Z", expected_changes: [], manual_baseline: null, changed_at: null };

describe("releaseStatus", () => {
  it.each([
    ["regression", { state: "FAIL", reason: "confirmed" }, "Regression", "fail", null],
    [
      "early regression",
      { state: "FAIL", reason: "confirmed", early: true },
      "Regression",
      "fail",
      "Confirmed early, before the full sample was in.",
    ],
    [
      "live healthy",
      { state: "PASS", reason: "confirmed" },
      "Healthy",
      "pass",
      "A regression found before monitoring ends can still change this.",
    ],
    ["final healthy", { state: "PASS", reason: "confirmed", final: true }, "Healthy", "pass", null],
    [
      "ended without a verdict",
      { reason: "window_elapsed", final: true },
      "Unconfirmed",
      "calm",
      "No regression was found, but monitoring ended before there was enough data to confirm it healthy.",
    ],
    [
      "first release",
      { state: "PENDING", reason: "no_baseline" },
      "First release",
      "neutral",
      "Nothing to compare yet; it becomes the baseline for the next release.",
    ],
    [
      "no check yet",
      { state: "PENDING", reason: "insufficient_sample", evaluation: null },
      "Collecting",
      "neutral",
      "Waiting for the first check.",
    ],
    [
      "candidate sample",
      { state: "PENDING", reason: "insufficient_sample" },
      "Collecting",
      "neutral",
      "No verdict until the full sample is in, unless a strong regression shows up first.",
    ],
    [
      "baseline sample",
      { state: "PENDING", reason: "insufficient_baseline" },
      "Collecting",
      "neutral",
      "The baseline does not have enough turns or sessions yet.",
    ],
    ["possible regression", { reason: "fail_candidate" }, "Possible regression", "warning", "The next check confirms or clears it."],
    [
      "early possible regression",
      { reason: "fail_candidate", early: true },
      "Possible regression",
      "warning",
      "Seen early, after 38 turns; the next check confirms or clears it.",
    ],
    ["pass candidate", { reason: "pass_candidate" }, "Looks healthy", "calm", "No regression so far; the next check confirms it."],
    ["low power", {}, "Not enough data", "calm", "No regression so far, but small changes would not show yet."],
  ])("describes %s", (_, patch, title, tone, note) => {
    expect(releaseStatus(detail(patch))).toMatchObject({ title, tone, note });
  });

  it("names how monitoring ended", () => {
    expect(releaseStatus(detail()).phase).toEqual({ kind: "monitoring", label: "Monitoring" });
    expect(releaseStatus(detail({ user_state: stopped })).phase).toEqual({ kind: "stopping", label: "Stopping" });
    expect(releaseStatus(detail({ final: true, summary: { ended: { reason: "stopped", by: null } } })).phase).toEqual({
      kind: "stopped",
      label: "Stopped",
    });
    expect(releaseStatus(detail({ final: true, summary: { ended: { reason: "superseded", by: "v1.10.0" } } })).phase).toEqual({
      kind: "replaced",
      label: "Replaced by",
      by: "v1.10.0",
    });
    expect(releaseStatus(detail({ final: true, summary: { ended: { reason: "window_elapsed", by: null } } })).phase).toEqual({
      kind: "ended",
      label: "Ended",
    });
  });
});
