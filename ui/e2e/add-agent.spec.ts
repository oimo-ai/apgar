import { randomBytes } from "node:crypto";
import fs from "node:fs";
import path from "node:path";

import { expect, test } from "@playwright/test";

import { api } from "./helpers";

test("OTLP flow", async ({ page }) => {
  test.setTimeout(150_000);
  await api(page, "/api/v1/agents/e2e-agent", { method: "DELETE" });
  await page.goto("/add-agent");
  await page.getByTestId("add-agent-name").fill("e2e-agent");
  await page.getByTestId("add-agent-source-otlp").check();
  await page.getByTestId("add-agent-environment").fill("production");
  await page.getByTestId("add-agent-release-from").selectOption("gen_ai.agent.version");
  await page.getByTestId("add-agent-submit").click();
  await expect(page.getByTestId("add-agent-token")).toHaveText(/apg_ing_/);
  await expect(page.getByTestId("add-agent-snippet")).toContainText("/v1/traces");
  await expect(page.getByTestId("add-agent-snippet")).toContainText("gen_ai.agent.name=e2e-agent");
  await expect(page.getByTestId("add-agent-waiting")).toBeVisible();
  const token = (await page.getByTestId("add-agent-token").innerText()).trim();
  const fixture = fs.readFileSync(path.resolve(process.cwd(), "../tests/fixtures/otlp/genai_basic.json"), "utf8");
  const start = BigInt(Date.now() - 15 * 60 * 1000) * 1_000_000n;
  const end = start + 2_400_000_000n;
  const body = fixture
    .replaceAll("billing-copilot", "e2e-agent")
    .replaceAll("11111111111111111111111111111111", randomBytes(16).toString("hex"))
    .replaceAll("aaaaaaaaaaaaaaaa", randomBytes(8).toString("hex"))
    .replaceAll(/"startTimeUnixNano": "[0-9]+"/g, `"startTimeUnixNano": "${start.toString()}"`)
    .replaceAll(/"endTimeUnixNano": "[0-9]+"/g, `"endTimeUnixNano": "${end.toString()}"`);
  const posted = await page.request.post("/v1/traces", {
    headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
    data: body,
  });
  expect(posted.ok()).toBeTruthy();
  await expect(page.getByTestId("add-agent-first-turn")).toBeVisible({ timeout: 90_000 });
  const deleted = await api(page, "/api/v1/agents/e2e-agent", { method: "DELETE" });
  expect(deleted.status()).toBe(204);
});
