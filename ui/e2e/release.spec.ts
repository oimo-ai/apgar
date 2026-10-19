import { expect, test, type Page } from "@playwright/test";

const METRICS = [
  "tool_calls_per_turn",
  "zero_tool_turn_rate",
  "tool_retry_rate",
  "loop_rate",
  "output_tokens_p50",
  "format_failure_rate",
  "turns_per_session",
  "tool_error_rate",
  "llm_error_rate",
  "cost_per_turn",
  "latency_p95",
];

const A2 = "/agents/billing-copilot/releases/fp-8e2f0c6a1b93";
const A4 = "/agents/billing-copilot/releases/fp-c4b2a9e8d711";
const B3 = "/agents/support-agent/releases/b7c6d5e";

async function checkCount(page: Page): Promise<number> {
  const label = (await page.getByTestId("monitoring-track").getAttribute("aria-label")) ?? "";
  return Number(/(\d+) checks$/.exec(label)?.[1] ?? 0);
}

function marker(page: Page, title: string) {
  return page.locator(`[data-testid^='monitoring-marker-'][aria-label*='${title}']`).first();
}

test.describe.serial("release page", () => {
  test("Regression header", async ({ page }) => {
    await page.goto(A2);
    await expect(page.getByTestId("release-status")).toHaveAttribute("data-state", "FAIL");
    await expect(page.getByTestId("release-status-title")).toHaveText("Regression");
    await expect(page.getByTestId("baseline-select")).toHaveValue("fp-3c1e9a7b2d44");
    await expect(page.getByTestId("baseline-select")).toBeDisabled();
    await expect(page.getByTestId("release-sample")).toHaveText(/\d{1,3}(,\d{3})* turns/);
    await expect(page.getByTestId("release-timing")).toContainText("Ended after");
    await expect(
      page.getByTestId("monitoring-track").locator("[data-testid='monitoring-segment'][data-kind='regression']").first(),
    ).toBeAttached();
    await expect(page.getByTestId("monitoring-marker-end")).toBeVisible();
    await expect(page.getByTestId("monitoring-now")).toHaveCount(0);
    await expect(page.getByTestId("action-stop")).toBeDisabled();
  });

  test("Metrics table formatting", async ({ page }) => {
    await page.goto(A2);
    const error = page.getByTestId("metric-row-tool_error_rate");
    await expect(error).toContainText(/pp\s*$|pp/);
    await expect(page.getByTestId("metric-status-tool_error_rate")).toContainText("regressed");
    const tokens = page.getByTestId("metric-row-output_tokens_p50");
    await expect(tokens).toContainText("%");
    await expect(tokens).toContainText("tokens");
    const ids = await page.locator("[data-testid^='metric-row-']").evaluateAll((rows) =>
      rows.map((row) => row.getAttribute("data-testid")?.replace("metric-row-", "")),
    );
    const present = METRICS.filter((id) => ids.includes(id));
    expect(ids).toEqual(present);
  });

  test("Slices", async ({ page }) => {
    await page.goto(A2);
    const tool = page.getByTestId("slice-dimension-tool");
    await expect(tool.getByTestId("slice-row-tool-sql_query")).toBeVisible();
    const first = tool.locator("[data-testid^='slice-row-tool-']").first();
    await expect(first).toHaveAttribute("data-testid", "slice-row-tool-sql_query");
    await expect(first).toHaveAttribute("data-status", "FAIL");
    await expect(page.getByTestId("slice-dimension-session_depth")).toBeVisible();
  });

  test("Checks on the monitoring window", async ({ page }) => {
    await page.goto(A2);
    await expect(page.getByTestId("monitoring-segment").first()).toBeAttached();
    await expect.poll(async () => checkCount(page)).toBeGreaterThanOrEqual(2);
    await expect(page.getByTestId("release-last-check")).toHaveAttribute("aria-label", /Trigger (Scheduled|Manual)/);
  });

  // Runs before the stop test, which ends monitoring on A4.
  test("Manual baseline", async ({ page }) => {
    test.setTimeout(90_000);
    await page.goto(B3);
    await expect(page.getByTestId("baseline-select").locator("option", { hasText: "d4e5f6a" })).toHaveCount(0);
    await page.goto(A4);
    const select = page.getByTestId("baseline-select");
    await expect(select).toBeEnabled();
    await expect(select).not.toHaveValue("");
    const current = await select.inputValue();
    const target = current === "fp-8e2f0c6a1b93" ? "fp-3c1e9a7b2d44" : "fp-8e2f0c6a1b93";
    await select.selectOption(target);
    await expect(page.getByTestId("confirm-dialog")).toContainText(`the traffic ${target} served in the 7 days before`);
    await page.getByTestId("confirm-cancel").click();
    await expect(select).toHaveValue(current);
    await expect.poll(async () => checkCount(page)).toBeGreaterThan(0);
    const before = await checkCount(page);
    await select.selectOption(target);
    await page.getByTestId("confirm-accept").click();
    await expect(page.getByTestId("queued-indicator")).toBeVisible();
    await expect(marker(page, "Baseline changed")).toBeVisible();
    await expect.poll(async () => checkCount(page), { timeout: 30_000 }).toBeGreaterThan(before);
    await expect(page.getByTestId("release-last-check")).toHaveAttribute("aria-label", /Trigger Manual/);
    await expect(select).toHaveValue(target);
    await expect(page.getByTestId("release-baseline")).toContainText("manual");
  });

  test("Stop monitoring", async ({ page }) => {
    test.setTimeout(90_000);
    await page.goto(A4);
    await expect(page.getByTestId("monitoring-now")).toBeVisible();
    await page.getByTestId("action-stop").click();
    await expect(page.getByTestId("confirm-dialog")).toContainText("can still end as a regression");
    await page.getByTestId("confirm-cancel").click();
    await expect(page.getByTestId("release-final")).toHaveCount(0);
    await page.getByTestId("action-stop").click();
    await page.getByTestId("confirm-accept").click();
    await expect(page.locator("[data-sonner-toast]")).toBeVisible();
    await expect(page.getByTestId("release-final")).toBeVisible({ timeout: 30_000 });
    await expect(page.getByTestId("release-timing")).toContainText("Stopped after");
    await expect(marker(page, "Monitoring stopped")).toBeVisible();
    await expect(page.getByTestId("action-stop")).toBeDisabled();
  });

  test("Expected changes", async ({ page }) => {
    test.setTimeout(90_000);
    await page.goto(B3);
    await page.getByTestId("action-expected").click();
    await page.getByTestId("expected-metric-output_tokens_p50").check();
    await page.getByTestId("dialog-confirm").click();
    await expect(marker(page, "Expected changes updated")).toBeVisible();
    await expect(page.getByTestId("metric-status-output_tokens_p50")).toContainText("expected", { timeout: 30_000 });
  });
});
