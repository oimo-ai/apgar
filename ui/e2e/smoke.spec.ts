import { expect, test } from "@playwright/test";

import { adminToken } from "./helpers";

test.skip(process.env.APGAR_SMOKE !== "1", "smoke project is invoked by scripts/smoke.sh");

test("P-S1 Fresh clone verdict", async ({ page }) => {
  await page.goto("/login");
  await page.getByTestId("login-token").fill(adminToken());
  await page.getByTestId("login-submit").click();
  await expect(page.getByTestId("page-agents")).toBeVisible();
  await expect(page.getByTestId("agent-row-billing-copilot")).toBeVisible();
  await page.goto("/agents/billing-copilot/releases/fp-8e2f0c6a1b93");
  await expect(page.getByTestId("page-release")).toBeVisible();
  await expect(page.getByTestId("release-status")).toHaveAttribute("data-state", "FAIL");
  await expect(page.getByTestId("release-status-title")).toHaveText("Regression");
});
