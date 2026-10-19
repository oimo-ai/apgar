import { expect, test } from "@playwright/test";

const RELEASES = ["fp-3c1e9a7b2d44", "fp-8e2f0c6a1b93", "fp-5a7d1e3f9c20", "fp-c4b2a9e8d711"];

test("Timeline", async ({ page }) => {
  await page.goto("/agents/billing-copilot");
  const timeline = page.getByTestId("agent-release-timeline");
  for (const release of RELEASES) {
    await expect(timeline.getByTestId(`release-row-${release}`)).toBeVisible();
  }
  await expect(timeline.getByTestId("release-row-fp-8e2f0c6a1b93").getByTestId("verdict-badge")).toHaveAttribute("data-state", "FAIL");
});

test("Metric coverage", async ({ page }) => {
  await page.goto("/agents/billing-copilot");
  await expect(page.getByTestId("metric-coverage")).toContainText(/\d+ of \d+ metrics active/);
});

test("Untagged and environment warnings on the agent page", async ({ page }) => {
  await page.goto("/agents/support-agent");
  await expect(page.getByTestId("agent-untagged-warning")).toBeVisible();
  await expect(page.getByTestId("agent-env-warning")).toBeVisible();
});
