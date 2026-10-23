import { render, screen } from "@testing-library/react";

import { InstrumentationSteps, MetricCoverage } from "@/components/MetricCoverage";

const coverage = {
  active: 7,
  total: 11,
  groups: { behavior: { active: 4, total: 7 }, reliability: { active: 2, total: 2 }, cost_latency: { active: 1, total: 2 } },
  metrics: [
    { id: "tool_retry_rate", group: "behavior", active: false, missing: "tool arguments", reason: "coverage", share: 0.4 },
    { id: "loop_rate", group: "behavior", active: false, missing: "tool arguments", reason: "coverage", share: 0.4 },
    { id: "format_failure_rate", group: "behavior", active: false, missing: "message content", reason: "no_content", share: null },
    { id: "latency_p95", group: "cost_latency", active: false, missing: null, reason: "disabled", share: null },
  ],
};

describe("MetricCoverage", () => {
  it("shows the compact line and the missing inputs per group", () => {
    render(<MetricCoverage coverage={coverage} />);
    expect(screen.getByTestId("metric-coverage")).toHaveTextContent("7 of 11 metrics active, 3 need more instrumentation");
    expect(screen.getByTestId("metric-coverage-behavior")).toHaveTextContent("Retry rate: missing tool arguments (present on 40.0%)");
    expect(screen.getByTestId("metric-coverage-behavior")).toHaveTextContent("Format failure rate: missing message content");
    expect(screen.getByTestId("metric-coverage-cost_latency")).toHaveTextContent("Latency p95: turned off for this agent");
  });

  it("explains coverage before the first check", () => {
    render(<MetricCoverage coverage={null} />);
    expect(screen.getByTestId("metric-coverage")).toHaveTextContent("after the first check");
  });

  it("lists the instrumentation steps for the source", () => {
    render(<InstrumentationSteps source="langfuse" coverage={null} />);
    expect(screen.getByTestId("metric-setup")).toHaveTextContent("Fetch content");
  });
});
