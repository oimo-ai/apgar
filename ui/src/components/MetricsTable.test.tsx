import { render, screen } from "@testing-library/react";

import type { MetricItem } from "@/api/types";
import { MetricsTable, metricRowStatus } from "@/components/MetricsTable";
import { METRIC_ORDER } from "@/lib/metrics";

function item(patch: Partial<MetricItem>): MetricItem {
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
    baseline: 0.01,
    candidate: 0.04,
    delta: 0.03,
    ci: [0.02, 0.04],
    status: "FAIL",
    turns_needed: 10,
    detectable_degradation: 0.02,
    n_candidate_units: 10,
    n_baseline_units: 10,
    trend: "flat",
    ...patch,
  };
}

describe("MetricsTable", () => {
  it("keeps the metric group order and formats pp versus percent", () => {
    const items = {
      cost_per_turn: item({ tolerance_mode: "rel", direction: "up", tolerance: 0.2, unit: "usd", delta: 0.1 }),
      tool_error_rate: item({}),
      output_tokens_p50: item({
        tolerance_mode: "rel",
        direction: "down",
        tolerance: 0.15,
        unit: "tokens",
        delta: -0.35,
        status: "PASS",
      }),
    };
    render(<MetricsTable items={items} />);
    const rows = screen.getAllByTestId(/metric-row-/).map((row) => row.getAttribute("data-testid"));
    const expected = METRIC_ORDER.filter((id) => id in items).map((id) => `metric-row-${id}`);
    expect(rows).toEqual(expected);
    expect(screen.getByTestId("metric-row-tool_error_rate")).toHaveTextContent("pp");
    expect(screen.getByTestId("metric-row-output_tokens_p50")).toHaveTextContent("%");
    expect(screen.getByTestId("metric-row-output_tokens_p50")).toHaveTextContent("tokens");
  });

  it.each([
    [{ status: "FAIL" }, true, "regressed"],
    [{ status: "FAIL" }, false, "possible"],
    [{ status: "FAIL", role: "informational" }, true, "informational"],
    [{ status: "PASS", role: "informational" }, true, "informational"],
    [{ status: "PASS" }, true, "within tolerance"],
    [{ status: "INCONCLUSIVE" }, true, "not enough data"],
    [{ status: "EXPECTED" }, true, "expected"],
    [{ status: "NA", applicable: false }, true, "unavailable"],
  ])("maps %o to the status vocabulary", (patch, confirmed, expected) => {
    expect(metricRowStatus(item(patch as Partial<MetricItem>), confirmed)).toBe(expected);
  });

  it("collapses unavailable metrics into one line per group", () => {
    render(
      <MetricsTable
        items={{
          tool_error_rate: item({ status: "PASS" }),
          tool_retry_rate: item({ status: "NA", applicable: false, na_reason: "coverage", baseline: null, candidate: null }),
          loop_rate: item({ status: "NA", applicable: false, na_reason: "coverage", baseline: null, candidate: null }),
        }}
        coverage={{
          active: 1,
          total: 3,
          groups: { behavior: { active: 0, total: 2 }, reliability: { active: 1, total: 1 } },
          metrics: [
            { id: "tool_retry_rate", group: "behavior", active: false, missing: "tool arguments", share: 0.1 },
            { id: "loop_rate", group: "behavior", active: false, missing: "tool arguments", share: 0.1 },
          ],
        }}
      />,
    );
    expect(screen.queryByTestId("metric-row-tool_retry_rate")).toBeNull();
    expect(screen.getByTestId("metrics-unavailable-behavior")).toHaveTextContent(
      "Retry rate and loop rate are unavailable: missing tool arguments.",
    );
  });

  it("shows raw values without a status while collecting", () => {
    render(<MetricsTable items={{ tool_error_rate: item({ status: "FAIL" }) }} collecting />);
    expect(screen.getByTestId("metric-status-tool_error_rate")).toHaveTextContent("so far");
    expect(screen.getByTestId("metric-row-tool_error_rate").className).not.toMatch(/fail/);
  });

  it("expands the selected metric with its detail", () => {
    render(
      <MetricsTable
        items={{ tool_error_rate: item({}) }}
        selected="tool_error_rate"
        onSelect={() => undefined}
        confirmed
        renderDetail={(id) => <p>detail for {id}</p>}
      />,
    );
    expect(screen.getByTestId("metric-detail-tool_error_rate")).toHaveTextContent("detail for tool_error_rate");
  });
});
