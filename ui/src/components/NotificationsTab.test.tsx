import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { NotificationsTab } from "@/components/NotificationsTab";

function renderTab(): void {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <NotificationsTab />
    </QueryClientProvider>,
  );
}

describe("NotificationsTab", () => {
  it("defaults to failed rows and offers retry only there", async () => {
    const user = userEvent.setup();
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/retry")) {
        return Promise.resolve(new Response("{}", { status: 202 }));
      }
      const failed = url.includes("status=failed") || !url.includes("status=");
      const items = failed
        ? [
            {
              id: "n1",
              agent: "billing-copilot",
              release: "fp-fail",
              event: "regression",
              channel: "slack",
              status: "failed",
              attempts: 1,
              next_attempt_at: "2026-10-08T09:30:00.000Z",
              last_error: "HTTP 404",
              created_at: "2026-10-08T09:30:00.000Z",
              updated_at: "2026-10-08T09:30:00.000Z",
            },
          ]
        : [];
      return Promise.resolve(
        new Response(JSON.stringify({ items, total: items.length }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      );
    });
    vi.stubGlobal("fetch", fetchMock);
    renderTab();
    expect(screen.getByTestId("notifications-filter-status")).toHaveValue("failed");
    expect(await screen.findByTestId("notification-row-n1")).toBeVisible();
    expect(screen.getByTestId("notification-retry-n1")).toBeVisible();
    expect(screen.getByTestId("pagination-range")).toHaveTextContent("1–1 of 1");
    expect(screen.queryByTestId("pagination-next")).toBeNull();
    await user.selectOptions(screen.getByTestId("notifications-filter-status"), "pending");
    expect(screen.queryByTestId("notification-retry-n1")).toBeNull();
    vi.unstubAllGlobals();
  });

  it("pages through rows and resets to the first page on filter change", async () => {
    const user = userEvent.setup();
    const total = 120;
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL) => {
      const params = new URL(String(input), "http://localhost").searchParams;
      const limit = Number(params.get("limit"));
      const offset = Number(params.get("offset") ?? 0);
      const items = Array.from({ length: Math.max(0, Math.min(limit, total - offset)) }, (_, index) => ({
        id: `n${offset + index}`,
        agent: "billing-copilot",
        release: "fp-fail",
        event: "regression",
        channel: "slack",
        status: params.get("status") ?? "sent",
        attempts: 1,
        next_attempt_at: null,
        last_error: null,
        created_at: "2026-10-08T09:30:00.000Z",
        updated_at: "2026-10-08T09:30:00.000Z",
      }));
      return Promise.resolve(
        new Response(JSON.stringify({ items, total }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      );
    });
    vi.stubGlobal("fetch", fetchMock);
    renderTab();
    expect(await screen.findByTestId("notification-row-n0")).toBeVisible();
    expect(screen.getByTestId("pagination-range")).toHaveTextContent("1–50 of 120");
    expect(screen.getByTestId("pagination-prev")).toBeDisabled();

    await user.click(screen.getByTestId("pagination-next"));
    expect(await screen.findByTestId("notification-row-n50")).toBeVisible();
    expect(screen.queryByTestId("notification-row-n0")).toBeNull();
    expect(screen.getByTestId("pagination-range")).toHaveTextContent("51–100 of 120");

    await user.click(screen.getByTestId("pagination-next"));
    expect(await screen.findByTestId("notification-row-n119")).toBeVisible();
    expect(screen.getByTestId("pagination-range")).toHaveTextContent("101–120 of 120");
    expect(screen.getByTestId("pagination-next")).toBeDisabled();

    await user.click(screen.getByTestId("pagination-prev"));
    expect(await screen.findByTestId("notification-row-n50")).toBeVisible();

    await user.selectOptions(screen.getByTestId("notifications-filter-status"), "sent");
    expect(await screen.findByTestId("notification-row-n0")).toBeVisible();
    expect(screen.getByTestId("pagination-range")).toHaveTextContent("1–50 of 120");
    const lastUrl = String(fetchMock.mock.calls.at(-1)?.[0]);
    expect(lastUrl).toContain("status=sent");
    expect(lastUrl).toContain("offset=0");
    vi.unstubAllGlobals();
  });
});
