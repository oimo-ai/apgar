import { expect, test } from "@playwright/test";

test("Table content", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByTestId("agent-row-billing-copilot")).toBeVisible();
  await expect(page.getByTestId("agent-row-support-agent")).toBeVisible();
  await expect(page.getByTestId("agent-row-billing-copilot").getByTestId("demo-badge")).toBeVisible();
  await expect(page.getByTestId("agent-row-support-agent").getByTestId("demo-badge")).toBeVisible();
  await expect(page.getByTestId("agent-latest-verdict-billing-copilot")).toHaveAttribute("data-state", "PASS");
});

test("Metric coverage column", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByTestId("agent-coverage-billing-copilot")).toHaveText(/\d+ of \d+ active/);
});

test("Setup warning indicator", async ({ page }) => {
  await page.goto("/");
  const warning = page.getByTestId("agent-warning-support-agent");
  await expect(warning).toBeVisible();
  await expect(warning).toHaveAttribute("title", /Untagged share above 5%/);
  await expect(warning).toHaveAttribute("title", /Multiple environments observed/);
  await expect(warning).toHaveAttribute("href", /\/agents\/support-agent$/);
});

test("Row navigation", async ({ page }) => {
  await page.goto("/");
  await page.getByTestId("agent-row-billing-copilot").click();
  await expect(page).toHaveURL(/\/agents\/billing-copilot$/);
  await expect(page.getByTestId("page-agent")).toBeVisible();
});

test("Keyboard navigation", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByTestId("agent-row-billing-copilot")).toBeVisible();
  for (let i = 0; i < 40; i += 1) {
    const focused = await page.evaluate(() => document.activeElement?.getAttribute("data-testid"));
    if (focused === "agent-row-billing-copilot") {
      break;
    }
    await page.keyboard.press("Tab");
  }
  await expect(page.getByTestId("agent-row-billing-copilot")).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("page-agent")).toBeVisible();
});
