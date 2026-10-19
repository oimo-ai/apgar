import { render, screen } from "@testing-library/react";

import { VerdictBadge } from "@/components/VerdictBadge";

describe("VerdictBadge", () => {
  it.each([
    ["FAIL", "confirmed", false, "Regression"],
    ["PASS", "confirmed", false, "Healthy"],
    ["PENDING", "no_baseline", false, "First release"],
    ["PENDING", "insufficient_sample", false, "Collecting"],
    ["INCONCLUSIVE", "fail_candidate", false, "Possible regression"],
    ["INCONCLUSIVE", "pass_candidate", false, "Looks healthy"],
    ["INCONCLUSIVE", "insufficient_power", false, "Not enough data"],
    ["INCONCLUSIVE", "superseded", true, "Unconfirmed"],
    ["INCONCLUSIVE", "stopped", true, "Unconfirmed"],
  ])("labels %s %s as %s", (state, reason, final, label) => {
    render(<VerdictBadge state={state} reason={reason} final={final} />);
    const badge = screen.getByTestId("verdict-badge");
    expect(badge).toHaveTextContent(new RegExp(`^${label}$`));
    expect(badge).toHaveAttribute("data-state", state);
  });

  it("carries the early marker and the suffix", () => {
    render(<VerdictBadge state="INCONCLUSIVE" reason="fail_candidate" early suffix="38 turns" />);
    expect(screen.getByTestId("verdict-badge")).toHaveTextContent("Possible regression, early: 38 turns");
  });

  it("keeps calm states free of the fail and warning colors", () => {
    render(<VerdictBadge state="INCONCLUSIVE" reason="window_elapsed" final />);
    expect(screen.getByTestId("verdict-badge").className).not.toMatch(/fail|inconclusive/);
  });
});
