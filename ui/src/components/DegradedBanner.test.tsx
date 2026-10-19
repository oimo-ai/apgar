import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";

import { apiFetch } from "@/api/client";
import { DegradedBanner } from "@/components/DegradedBanner";

vi.mock("@/api/client", () => ({
  apiFetch: vi.fn(),
  ApiError: class ApiError extends Error {},
  onSessionCleared: () => () => undefined,
}));

function renderBanner() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <DegradedBanner />
    </QueryClientProvider>,
  );
}

describe("DegradedBanner", () => {
  it("is hidden when storage is ok", async () => {
    vi.mocked(apiFetch).mockResolvedValue({ storage: "ok" });
    renderBanner();
    await waitFor(() => expect(apiFetch).toHaveBeenCalled());
    expect(screen.queryByTestId("degraded-banner")).not.toBeInTheDocument();
  });

  it("is visible when storage is not ok", async () => {
    vi.mocked(apiFetch).mockResolvedValue({ storage: "unavailable" });
    renderBanner();
    expect(await screen.findByTestId("degraded-banner")).toHaveTextContent("Storage unavailable");
  });

  it("is visible when the status query fails", async () => {
    vi.mocked(apiFetch).mockRejectedValue(new Error("down"));
    renderBanner();
    expect(await screen.findByTestId("degraded-banner")).toBeInTheDocument();
  });
});
