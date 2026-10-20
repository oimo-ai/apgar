import { render, screen } from "@testing-library/react";

import type { MetricItem } from "@/api/types";
import { SlicesSection } from "@/components/SlicesSection";

const item = {
  tolerance_mode: "abs",
  unit: "rate",
  status: "FAIL",
} as MetricItem;

describe("SlicesSection", () => {
  it("keeps delivered order, labels an empty value, and marks a dimension not applicable", () => {
    render(
      <SlicesSection
        items={{ tool_error_rate: item }}
        metric="tool_error_rate"
        minTurns={1}
        slices={{
          tool_error_rate: {
            tool: {
              applicable: true,
              values: [
                { value: "sql_query", candidate: 0.1, baseline: 0.01, delta: 0.09, ci: [0.05, 0.1], p_value: 0.01, p_adjusted: 0.02, status: "FAIL", n_candidate: 10, n_baseline: 12 },
                { value: "", candidate: 0, baseline: 0, delta: 0, ci: null, p_value: null, p_adjusted: null, status: "NOT_FLAGGED", n_candidate: 1, n_baseline: 1 },
              ],
            },
            surface: { applicable: false, values: [] },
          },
        }}
      />,
    );
    const rows = screen.getAllByTestId(/slice-row-tool-/);
    expect(rows[0]).toHaveAttribute("data-testid", "slice-row-tool-sql_query");
    expect(rows[1]).toHaveTextContent("(none)");
    expect(screen.getByTestId("slice-dimension-surface")).toHaveTextContent("not applicable");
  });

  it("lists every applicable dimension and counts its regressions", () => {
    render(
      <SlicesSection
        items={{ tool_error_rate: item }}
        metric="tool_error_rate"
        minTurns={1}
        slices={{
          tool_error_rate: {
            tool: {
              applicable: true,
              values: [
                { value: "sql_query", candidate: 0.02, baseline: 0.02, delta: 0, ci: null, p_value: null, p_adjusted: null, status: "NOT_FLAGGED", n_candidate: 10, n_baseline: 12 },
              ],
            },
            surface: {
              applicable: true,
              values: [
                { value: "web", candidate: 0.3, baseline: 0.02, delta: 0.28, ci: [0.2, 0.35], p_value: 0.01, p_adjusted: 0.02, status: "FAIL", n_candidate: 80, n_baseline: 90 },
              ],
            },
          },
        }}
      />,
    );
    expect(screen.getByTestId("slice-dimension-surface")).toHaveTextContent("1 regressed");
    expect(screen.getByTestId("slice-row-surface-web")).toHaveAttribute("data-status", "FAIL");
    expect(screen.getByTestId("slice-row-tool-sql_query")).toBeInTheDocument();
  });

  it("moves values that were not compared into a footer grouped by reason", () => {
    const skipped = { candidate: null, baseline: null, delta: null, ci: null, p_value: null, p_adjusted: null, status: "INSUFFICIENT" };
    render(
      <SlicesSection
        items={{ tool_error_rate: { ...item, level: "tool" } }}
        metric="tool_error_rate"
        minTurns={100}
        slices={{
          tool_error_rate: {
            tool: {
              applicable: true,
              values: [
                { value: "web_search", candidate: 0.3, baseline: 0.02, delta: 0.28, ci: null, p_value: null, p_adjusted: null, status: "FAIL", n_candidate: 180, n_baseline: 110 },
                { ...skipped, value: "create_ticket", n_candidate: 97, n_baseline: 564, reason: "few_turns" },
                { ...skipped, value: "legacy", n_candidate: 300, n_baseline: 300 },
              ],
            },
            surface: {
              applicable: true,
              values: [{ ...skipped, value: "email", n_candidate: 400, n_baseline: 420, reason: "coverage" }],
            },
          },
        }}
      />,
    );
    expect(screen.getAllByTestId(/slice-row-/)).toHaveLength(1);
    expect(screen.queryByTestId("slice-dimension-surface")).not.toBeInTheDocument();
    const footer = screen.getByTestId("slices-not-compared");
    expect(footer).not.toHaveAttribute("open");
    expect(footer.querySelector("summary")).toHaveTextContent("3 values not compared · 3 dimensions not applicable");
    expect(screen.getByTestId("slices-reason-few_turns")).toHaveTextContent("Too few tool calls (needs 100 on each side)");
    expect(screen.getByTestId("slice-skipped-tool-create_ticket")).toHaveTextContent("564 / 97");
    expect(screen.getByTestId("slices-reason-coverage")).toHaveTextContent("Too few units carry the required input");
    expect(screen.getByTestId("slices-reason-unknown")).toHaveTextContent("Not enough data to compare");
  });

  it("says when nothing can be compared", () => {
    const { rerender } = render(
      <SlicesSection
        items={{ tool_error_rate: item }}
        metric="tool_error_rate"
        slices={{
          tool_error_rate: {
            tool: { applicable: true, values: [{ value: "sql", candidate: 0, baseline: 0, delta: 0, ci: null, p_value: null, p_adjusted: null, status: "INSUFFICIENT", n_candidate: 1, n_baseline: 1 }] },
          },
        }}
      />,
    );
    expect(screen.getByTestId("slices-section")).toHaveTextContent("No slice has enough data to compare yet.");
    rerender(<SlicesSection items={{}} metric="missing" slices={{}} />);
    expect(screen.getByTestId("slices-section")).toHaveTextContent("No slices for this metric.");
  });
});
