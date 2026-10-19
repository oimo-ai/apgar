import { render, screen, within } from "@testing-library/react";

import type { EvaluationOut, ReleaseDetail, VerdictSettings } from "@/api/types";
import { ReleaseStrip } from "@/components/release/ReleaseStrip";

const NOW = Date.parse("2026-10-08T13:00:00Z");

function check(evaluated_at: string, state: string, reason: string): EvaluationOut {
  return { evaluated_at, manual: false, seed: evaluated_at, state, reason, final: false, metrics: {} } as unknown as EvaluationOut;
}

function detail(patch: Partial<ReleaseDetail> = {}): ReleaseDetail {
  return {
    agent: "billing-copilot",
    release: "a1b2c3d",
    first_seen: "2026-10-08T01:00:00Z",
    last_seen: "2026-10-08T12:00:00Z",
    state: "INCONCLUSIVE",
    reason: "fail_candidate",
    final: false,
    final_at: null,
    baseline: { release: "9f8e7d6", mode: "previous_release", unverified: false },
    max_window_end: "2026-10-11T01:00:00Z",
    user_state: { expected_changes: [], manual_baseline: null, changed_at: null, stopped_at: null },
    timing: {
      since_first_seen_seconds: 0,
      until_max_window_seconds: 0,
      last_check_at: "2026-10-08T12:30:00Z",
      next_check_at: "2026-10-08T13:15:00Z",
    },
    evaluation: {
      n_candidate_turns: 80,
      n_baseline_turns: 240,
      n_candidate_sessions: 43,
      n_baseline_sessions: 39,
      window_end: null,
    } as EvaluationOut,
    summary: null,
    actions: { stop: { enabled: true } },
    ...patch,
  } as unknown as ReleaseDetail;
}

const summary = { tone: "warning", label: "Possible regression", confirmations: { done: 1, needed: 2 }, collecting: false } as const;

describe("ReleaseStrip", () => {
  it("draws both arms, the checks, and the live position", () => {
    const history = [
      check("2026-10-08T12:30:00Z", "INCONCLUSIVE", "fail_candidate"),
      check("2026-10-08T12:00:00Z", "INCONCLUSIVE", "insufficient_power"),
    ];
    render(<ReleaseStrip detail={detail()} summary={summary} history={history} settings={undefined} now={NOW} />);
    const sample = screen.getByTestId("release-sample");
    expect(sample).toHaveTextContent("full sample at 200 turns, 30 sessions");
    const bar = (name: string) => within(sample).getByRole("progressbar", { name });
    expect(bar("This release turns")).toHaveAttribute("aria-valuetext", "80/200 turns");
    expect(bar("This release turns")).toHaveAttribute("aria-valuenow", "80");
    expect(bar("This release sessions")).toHaveAttribute("aria-valuetext", "43 sessions");
    expect(bar("This release sessions")).toHaveAttribute("aria-valuenow", "30");
    expect(bar("Baseline turns")).toHaveAttribute("aria-valuetext", "240 turns");
    expect(bar("Baseline sessions")).toHaveAttribute("aria-valuetext", "39 sessions");
    expect(sample).not.toHaveTextContent("9f8e7d6");
    const track = screen.getByTestId("monitoring-track");
    expect(track).toHaveAccessibleName("Monitored 12 h of 72 h, 2 checks");
    expect(
      within(track)
        .getAllByTestId("monitoring-segment")
        .map((segment) => segment.dataset.kind),
    ).toEqual(["collecting", "not_enough_data", "possible_regression"]);
    expect(within(track).getByRole("generic", { name: /^Possible regression\. A metric looked worse/ })).toBeInTheDocument();
    expect(screen.getByTestId("monitoring-now")).toBeInTheDocument();
    expect(screen.getByTestId("release-timing")).toHaveTextContent("Ends in 60 h");
    expect(screen.getByTestId("release-checks")).toHaveTextContent("Next check in 15 min");
    expect(screen.getByTestId("release-confirmations")).toHaveTextContent("1 of 2 confirmations");
  });

  it("shows a baseline short of sessions even when it has the turns", () => {
    const evaluation = { ...detail().evaluation, n_baseline_turns: 900, n_baseline_sessions: 12 } as EvaluationOut;
    render(<ReleaseStrip detail={detail({ evaluation })} summary={summary} history={[]} settings={undefined} now={NOW} />);
    const sample = screen.getByTestId("release-sample");
    expect(within(sample).getByRole("progressbar", { name: "Baseline turns" })).toHaveAttribute("aria-valuetext", "900 turns");
    const sessions = within(sample).getByRole("progressbar", { name: "Baseline sessions" });
    expect(sessions).toHaveAttribute("aria-valuetext", "12/30 sessions");
    expect(sessions).toHaveTextContent("12/30 sessions");
  });

  it("names a stop that is still running and one that ended", () => {
    const { rerender } = render(
      <ReleaseStrip
        detail={detail({
          user_state: { expected_changes: [], manual_baseline: null, changed_at: null, stopped_at: "2026-10-08T12:50:00Z" },
        })}
        summary={summary}
        history={[]}
        settings={undefined}
        now={NOW}
      />,
    );
    expect(screen.getByTestId("release-timing")).toHaveTextContent("Stopping, final check queued");
    rerender(
      <ReleaseStrip
        detail={detail({
          final: true,
          final_at: "2026-10-08T12:51:00Z",
          reason: "stopped",
          user_state: { expected_changes: [], manual_baseline: null, changed_at: null, stopped_at: "2026-10-08T12:50:00Z" },
          summary: { ended: { reason: "stopped", by: null } } as ReleaseDetail["summary"],
        })}
        summary={{ ...summary, confirmations: null }}
        history={[]}
        settings={undefined}
        now={NOW}
      />,
    );
    expect(screen.getByTestId("release-timing")).toHaveTextContent("Stopped after 12 h");
    expect(screen.queryByTestId("monitoring-now")).toBeNull();
    expect(screen.queryByTestId("release-checks")).not.toHaveTextContent("Next check");
  });

  it("marks a baseline change on the track", () => {
    const history = [
      { ...check("2026-10-08T12:30:00Z", "INCONCLUSIVE", "pass_candidate"), baseline_release: "v2" },
      { ...check("2026-10-08T12:00:00Z", "PASS", "confirmed"), baseline_release: "v1" },
    ];
    const events = [{ ts: "2026-10-08T12:10:00Z", type: "manual_baseline", payload: { release: "v2" }, actor: "ana" }];
    render(
      <ReleaseStrip
        detail={detail({
          user_state: { expected_changes: [], manual_baseline: "v2", changed_at: "2026-10-08T12:10:00Z", stopped_at: null },
        })}
        summary={summary}
        history={history}
        events={events}
        settings={undefined}
        now={NOW}
      />,
    );
    expect(screen.getByTestId("monitoring-marker-baseline")).toHaveAccessibleName(
      "Baseline changed. To v2. Before v1. When Oct 8, 12:10 UTC. By ana. Confirmation started over.",
    );
    const stale = screen.getAllByTestId("monitoring-segment").filter((segment) => segment.dataset.stale);
    expect(stale.map((segment) => segment.dataset.kind)).toEqual(["healthy"]);
  });

  it("explains every item of the check line", () => {
    const evaluation = {
      ...detail().evaluation,
      manual: false,
      duration_ms: 820,
      n_excluded_mixed: 8,
      n_excluded_untagged: 0,
      n_excluded_late: 4,
    } as EvaluationOut;
    const late = detail({ evaluation, timing: { ...detail().timing, next_check_at: "2026-10-08T12:40:00Z" } });
    const { rerender } = render(<ReleaseStrip detail={late} summary={summary} history={[]} settings={undefined} now={NOW} />);
    expect(screen.getByTestId("release-last-check")).toHaveAccessibleName(
      "Last check. Trigger Scheduled. At Oct 8, 12:30 UTC. Took 820 ms. Left out 12 turns. " +
        "8 from mixed sessions, which also ran another release. 4 late, sent long after they ran.",
    );
    expect(screen.getByTestId("release-next-check")).toHaveTextContent("Next check overdue");
    expect(screen.getByTestId("release-next-check")).toHaveAccessibleName(
      "Next check is late. Was due Oct 8, 12:40 UTC. This check should have run by now. The worker may be behind or stopped.",
    );
    expect(screen.getByTestId("release-last-turn")).toHaveAccessibleName(
      "Last turn. The latest turn received from this release. At Oct 8, 12:00 UTC. Checks pause after 24 h without new turns.",
    );
    expect(screen.getByTestId("release-confirmations")).toHaveAccessibleName(
      "Confirmation. A regression is confirmed after 2 checks in a row find it. So far 1 of 2. Changing the baseline or the expected changes starts over.",
    );
    const settings = { include_mixed_sessions: true } as VerdictSettings;
    rerender(<ReleaseStrip detail={late} summary={summary} history={[]} settings={settings} now={NOW} />);
    expect(screen.getByTestId("release-last-check")).toHaveAccessibleName(
      "Last check. Trigger Scheduled. At Oct 8, 12:30 UTC. Took 820 ms. Left out 4 turns. " +
        "4 late, sent long after they ran. 8 turns from mixed sessions are counted, because this agent includes mixed sessions.",
    );
  });

  it("says when checks are paused for lack of traffic", () => {
    render(
      <ReleaseStrip detail={detail({ last_seen: "2026-10-07T12:00:00Z" })} summary={summary} history={[]} settings={undefined} now={NOW} />,
    );
    expect(screen.getByTestId("release-checks")).toHaveTextContent("Checks paused: no traffic for over 24 h");
    expect(screen.getByTestId("release-checks")).not.toHaveTextContent("Next check");
    expect(screen.getByTestId("monitoring-now")).toHaveAccessibleName("Now. No traffic for over 24 h, so checks are paused.");
  });
});
