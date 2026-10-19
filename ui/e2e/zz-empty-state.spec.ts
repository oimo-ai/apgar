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
    await expect(page.getByTestId("seed-demo-button")).toBeVisible();
    await page.getByTestId("seed-demo-button").click();
    await expect(page.getByText("Seeding demo data, this takes about two minutes")).toBeVisible();
    await expect(page.getByTestId("agent-row-billing-copilot")).toBeVisible({ timeout: 8 * 60_000 });
  });
});
