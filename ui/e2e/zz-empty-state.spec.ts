import path from "node:path";

import { expect, test } from "@playwright/test";

import { api, purgeDemo } from "./helpers";

test.describe.serial("empty state", () => {
  test("Empty state", async ({ page }) => {
    test.setTimeout(12 * 60_000);
    const configFile = test.info().config.configFile;
    purgeDemo(configFile ? path.dirname(configFile) : process.cwd());
    const response = await api(page, "/api/v1/agents?limit=500");
    const body = (await response.json()) as { items: unknown[] };
    expect(body.items).toHaveLength(0);
    await page.goto("/");
    await expect(page.getByTestId("agents-empty")).toBeVisible();
    await expect(page.getByTestId("add-agent-open")).toBeHidden();
    await expect(page.getByTestId("empty-add-agent")).toBeVisible();
    await expect(page.getByTestId("empty-privacy")).toBeVisible();
    await page.getByTestId("seed-demo-button").click();
    await expect(page.getByTestId("seed-demo-progress")).toBeVisible();
    // The agents show up while their verdicts are still being replayed.
    await expect(page.getByTestId("agent-row-billing-copilot")).toBeVisible({ timeout: 2 * 60_000 });
    await expect(page.getByTestId("demo-seeding-notice")).toBeVisible();
    await expect(page).toHaveURL(/\/agents\/billing-copilot\/releases\/[^/]+$/, { timeout: 8 * 60_000 });
    await expect(page.getByTestId("release-status")).toHaveAttribute("data-state", "FAIL");
    await page.goto("/");
    await expect(page.getByTestId("agents-demo-notice")).toBeVisible({ timeout: 8 * 60_000 });
    await expect(page.getByTestId("demo-seeding-notice")).toBeHidden();
  });
});
