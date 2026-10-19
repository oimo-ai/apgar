import { render, screen } from "@testing-library/react";

import { AgentSyncStatus } from "@/components/AgentSyncStatus";

const sync = {
  status: "error",
  watermark: "2026-10-08T09:00:00.000Z",
  last_success_at: "2026-10-08T09:00:00.000Z",
  lag_seconds: 90,
  last_error: "HTTP 429",
};

describe("AgentSyncStatus", () => {
  it("renders watermark, lag, and the error for a Langfuse agent", () => {
    render(<AgentSyncStatus source="langfuse" sync={sync} />);
    const card = screen.getByTestId("agent-sync-status");
    expect(card).toHaveTextContent("2026-10-08 09:00 UTC");
    expect(card).toHaveTextContent("90s");
    expect(screen.getByTestId("sync-error")).toHaveTextContent("HTTP 429");
  });

  it("is hidden for an OTLP agent", () => {
    render(<AgentSyncStatus source="otlp" sync={null} />);
    expect(screen.queryByTestId("agent-sync-status")).not.toBeInTheDocument();
  });
});
