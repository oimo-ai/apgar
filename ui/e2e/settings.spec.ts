import { expect, test } from "@playwright/test";

import { api } from "./helpers";

test("Ingest token once", async ({ page }) => {
  await page.goto("/settings?tab=ingest-tokens");
  await page.getByTestId("settings-tab-ingest-tokens").click();
  await page.getByTestId("ingest-token-add").click();
  await page.getByTestId("ingest-token-name").fill("e2e");
  await page.getByTestId("ingest-token-create").click();
  await expect(page.getByTestId("token-plaintext")).toHaveText(/^apg_ing_/);
  const id = await page.locator("[data-testid^='ingest-token-row-']").last().getAttribute("data-testid");
  await page.reload();
  await expect(page.getByTestId("token-plaintext")).toHaveCount(0);
  const rowId = id?.replace("ingest-token-row-", "");
  await page.getByTestId(`ingest-token-revoke-${rowId}`).click();
  await expect(page.getByTestId(`ingest-token-row-${rowId}`)).toContainText("revoked");
});

test("Unknown settings tab falls back to Connections", async ({ page }) => {
  await page.goto("/settings?tab=missing");
  await expect(page.getByTestId("settings-tab-connections")).toHaveAttribute("aria-selected", "true");
  await expect(page.getByTestId("connection-add")).toBeVisible();
});

test("Connection test error", async ({ page }) => {
  const name = `e2e-wh-${Date.now().toString(36)}`;
  await page.goto("/settings?tab=connections");
  await page.getByTestId("connection-add").click();
  await page.getByTestId("connection-type").selectOption("webhook");
  await page.getByTestId("connection-name").fill(name);
  await page.getByTestId("connection-field-url").fill("http://127.0.0.1:9");
  await page.getByTestId("connection-field-secret").fill("0123456789abcdef");
  await page.getByTestId("connection-save").click();
  const row = page.locator("[data-testid^='connection-row-']", { hasText: name });
  await expect(row).toBeVisible();
  const id = ((await row.getAttribute("data-testid")) ?? "").replace("connection-row-", "");
  await page.getByTestId(`connection-test-${id}`).click();
  await expect(page.getByTestId(`connection-test-result-${id}`)).toContainText("error");
});

test("Agent tolerance persisted", async ({ page }) => {
  await page.goto("/settings?tab=agents");
  await page.getByTestId("agent-settings-select").selectOption("support-agent");
  await page.getByTestId("agent-settings-nav-metrics").click();
  await page.getByTestId("metric-tolerance-tool_error_rate").fill("3");
  await page.getByTestId("agent-settings-save").click();
  await expect(page.getByTestId("agent-settings-saved")).toBeVisible();
  await page.reload();
  await page.getByTestId("agent-settings-select").selectOption("support-agent");
  await expect(page.getByTestId("metric-tolerance-tool_error_rate")).toHaveValue("3");
  const response = await api(page, "/api/v1/agents/support-agent");
  const body = (await response.json()) as { effective_metrics: { tool_error_rate: { tolerance: number } } };
  expect(body.effective_metrics.tool_error_rate.tolerance).toBeCloseTo(0.03);
  await page.getByTestId("metric-tolerance-tool_error_rate").fill("2");
  await page.getByTestId("agent-settings-save").click();
  await expect(page.getByTestId("agent-settings-saved")).toBeVisible();
});

test("General settings", async ({ page }) => {
  await api(page, "/api/v1/settings", {
    method: "PATCH",
    data: {
      retention: { trace_data_days: 90, verdict_history_days: 400 },
      telemetry: { enabled: true },
    },
  });
  await page.goto("/settings?tab=general");
  await expect(page.getByTestId("retention-trace_data_days")).toHaveValue("90");
  await expect(page.getByTestId("retention-verdict_history_days")).toHaveValue("400");
  await page.getByRole("button", { name: "About Trace Data" }).hover();
  await expect(page.getByRole("tooltip")).toContainText("at least 21 days");
  await page.getByRole("button", { name: "About Verdict History" }).hover();
  await expect(page.getByRole("tooltip")).toContainText("Cannot be shorter than Trace Data");
  await page.getByTestId("retention-trace_data_days").fill("20");
  await page.getByTestId("general-save").click();
  await expect(page.locator("[data-sonner-toast]").last()).toContainText("must be in [21, 3650]");
  await expect(page.locator("[data-sonner-toast]").last()).toContainText("conversation history");
  await page.reload();
  await expect(page.getByTestId("retention-trace_data_days")).toHaveValue("90");
  await page.getByTestId("retention-verdict_history_days").fill("50");
  await page.getByTestId("general-save").click();
  await expect(page.locator("[data-sonner-toast]").last()).toContainText("trace_data_days (90)");
  await page.getByTestId("retention-trace_data_days").fill("120");
  await page.getByTestId("retention-verdict_history_days").fill("400");
  await page.getByTestId("general-save").click();
  await expect(page.getByTestId("general-saved")).toBeVisible();
  await page.reload();
  await expect(page.getByTestId("retention-trace_data_days")).toHaveValue("120");
  await page.getByTestId("retention-trace_data_days").fill("90");
  await page.getByTestId("general-save").click();
  await expect(page.getByTestId("general-saved")).toBeVisible();
  await page.getByTestId("telemetry-toggle").click();
  await expect(page.getByTestId("telemetry-toggle")).toHaveAttribute("aria-checked", "false");
  await expect(page.getByTestId("general-dirty")).toBeVisible();
  await page.getByTestId("general-save").click();
  await expect.poll(async () => {
    const response = await api(page, "/api/v1/settings");
    const body = (await response.json()) as { telemetry: { enabled: boolean } };
    return body.telemetry.enabled;
  }).toBe(false);
  await page.getByTestId("telemetry-toggle").click();
  await expect(page.getByTestId("telemetry-toggle")).toHaveAttribute("aria-checked", "true");
  await page.getByTestId("general-save").click();
  await expect.poll(async () => {
    const response = await api(page, "/api/v1/settings");
    const body = (await response.json()) as { telemetry: { enabled: boolean } };
    return body.telemetry.enabled;
  }).toBe(true);
});
