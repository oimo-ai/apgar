import { expect, test } from "@playwright/test";

import { api } from "./helpers";

const SUPPORT = "support-agent";
const LIVE_RELEASE = "d4e5f6a";
const HOST = "host.docker.internal";

async function received(path: string): Promise<{ items?: { signature_valid?: boolean; event?: string }[] }> {
  const response = await fetch(`http://localhost:9098${path}`);
  return (await response.json()) as { items?: { signature_valid?: boolean; event?: string }[] };
}

test.describe.serial("actions", () => {
  let endedBefore = 0;

  test("Notifications tab", async ({ page }) => {
    test.setTimeout(120_000);
    const slack = await api(page, "/api/v1/connections", {
      method: "POST",
      data: {
        name: `slack-${Date.now()}`,
        type: "slack",
        config: { webhook_url: `http://${HOST}:9098/slack-revoked` },
      },
    });
    expect(slack.ok()).toBeTruthy();
    const created = (await slack.json()) as { id: string };
    const patched = await api(page, `/api/v1/agents/${SUPPORT}`, {
      method: "PATCH",
      data: { slack_connection: created.id },
    });
    expect(patched.ok()).toBeTruthy();
    const hook = await api(page, "/api/v1/connections", {
      method: "POST",
      data: {
        name: `hook-${Date.now()}`,
        type: "webhook",
        config: { url: `http://${HOST}:9098/webhook`, secret: "0123456789abcdef" },
      },
    });
    expect(hook.ok()).toBeTruthy();
    const before = await received("/webhook/received");
    endedBefore = (before.items ?? []).filter((item) => item.event === "ended").length;
    const stop = await api(page, `/api/v1/agents/${SUPPORT}/releases/${LIVE_RELEASE}/stop`, {
      method: "POST",
      data: { reason: "stopped for the notification tests" },
    });
    expect(stop.ok()).toBeTruthy();
    await page.goto("/settings?tab=notifications");
    await expect(page.getByTestId("notifications-filter-status")).toHaveValue("failed");
    const row = page.locator("[data-testid^='notification-row-']").first();
    await expect(row).toBeVisible({ timeout: 90_000 });
    await expect(row.locator("td").nth(6)).toHaveText("1");
    await expect(row.locator("td").nth(8)).toContainText("404");
    const testId = await row.getAttribute("data-testid");
    await page.locator("[data-testid^='notification-retry-']").first().click();
    await expect(page.getByTestId(testId ?? "")).toHaveCount(0, { timeout: 10_000 });
  });

  test("Webhook signature", async () => {
    test.setTimeout(90_000);
    await expect
      .poll(
        async () => {
          const body = await received("/webhook/received");
          return (body.items ?? []).filter((item) => item.event === "ended" && item.signature_valid).length;
        },
        { timeout: 60_000 },
      )
      .toBeGreaterThan(endedBefore);
  });
});
