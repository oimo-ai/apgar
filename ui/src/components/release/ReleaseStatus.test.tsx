import { render, screen } from "@testing-library/react";

import type { ReleaseDetail } from "@/api/types";
import { ReleaseStatus } from "@/components/release/ReleaseStatus";

vi.mock("@tanstack/react-router", () => ({
  Link: ({ children, params }: { children: string; params: { release: string } }) => <a href={params.release}>{children}</a>,
}));

function detail(patch: Record<string, unknown> = {}): ReleaseDetail {
  return {
    agent: "billing-copilot",
    release: "a1b2c3d",
    state: "INCONCLUSIVE",
    reason: "insufficient_power",
    final: false,
    summary: null,
    user_state: { expected_changes: [], manual_baseline: null, changed_at: null, stopped_at: null },
    evaluation: { n_candidate_turns: 10 },
    ...patch,
  } as unknown as ReleaseDetail;
}

describe("ReleaseStatus", () => {
  it("shows a live status, a detectability note, a stop, and the release that replaced it", () => {
    const { rerender } = render(<ReleaseStatus detail={detail()} />);
    expect(screen.getByTestId("release-status-title")).toHaveTextContent("Not enough data");
    expect(screen.getByTestId("release-phase")).toHaveTextContent("Monitoring");

    rerender(
      <ReleaseStatus
        detail={detail({ summary: { detectability: "A 2 pp change would show." } })}
      />,
    );
    expect(screen.getByTestId("release-status-note")).toHaveTextContent("small changes would not show yet");

    rerender(<ReleaseStatus detail={detail({ user_state: { expected_changes: [], manual_baseline: null, changed_at: null, stopped_at: "2026-10-08T03:00:00Z" } })} />);
    expect(screen.getByTestId("release-phase")).toHaveTextContent("Stopping");

    rerender(
      <ReleaseStatus
        detail={detail({
          final: true,
          state: "INCONCLUSIVE",
          reason: "superseded",
          summary: { ended: { reason: "superseded", by: "v1.10.0" } },
        })}
      />,
    );
    expect(screen.getByTestId("release-final")).toHaveTextContent("Replaced by");
    expect(screen.getByRole("link", { name: "v1.10.0" })).toHaveAttribute("href", "v1.10.0");
  });
});
