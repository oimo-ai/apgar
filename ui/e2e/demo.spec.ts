import { expect, test } from "@playwright/test";

test("Demo badges on agent and release pages", async ({ page }) => {
  await page.goto("/agents/billing-copilot");
  await expect(page.getByTestId("page-agent").getByTestId("demo-badge")).toBeVisible();

  await page.goto("/agents/billing-copilot/releases/fp-8e2f0c6a1b93");
  await expect(page.getByTestId("page-release")).toBeVisible();
  await expect(page.locator(".app-topbar").getByTestId("demo-badge")).toBeVisible();
});
