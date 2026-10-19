import { expect, test } from "@playwright/test";

const PAGES = [
  ["/", "page-agents"],
  ["/agents/billing-copilot", "page-agent"],
  ["/agents/billing-copilot/releases/fp-8e2f0c6a1b93", "page-release"],
] as const;

test("System preference", async ({ browser }) => {
  const dark = await browser.newContext({ colorScheme: "dark" });
  const darkPage = await dark.newPage();
  await darkPage.goto("/login");
  await expect(darkPage.locator("html")).toHaveAttribute("data-theme", "dark");
  await dark.close();

  const light = await browser.newContext({ colorScheme: "light" });
  const page = await light.newPage();
  await page.goto("/login");
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await page.getByTestId("theme-toggle").click();
  await page.getByTestId("theme-option-dark").click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  const stored = await page.evaluate(() => localStorage.getItem("apgar-theme"));
  expect(stored).toBe("dark");
  await light.close();
});

test("Render budget", async ({ page }) => {
  const agent = process.env.APGAR_PERF_AGENT ?? "billing-copilot";
  const release = process.env.APGAR_PERF_RELEASE ?? "fp-8e2f0c6a1b93";
  const pages =
    process.env.APGAR_PERF_AGENT === undefined
      ? PAGES
      : ([
          ["/", "page-agents"],
          [`/agents/${agent}`, "page-agent"],
          [`/agents/${agent}/releases/${release}`, "page-release"],
        ] as const);
  for (const [path, testid] of pages) {
    await page.goto(path);
    await expect(page.getByTestId(testid)).toBeVisible();
  }
  const samples: number[] = [];
  const labeled: string[] = [];
  for (const [path, testid] of pages) {
    const started = Date.now();
    await page.goto(path, { waitUntil: "commit" });
    await expect(page.getByTestId(testid)).toBeVisible();
    const elapsed = Date.now() - started;
    samples.push(elapsed);
    labeled.push(`${path}=${elapsed}`);
    if (!process.env.APGAR_PERF_AGENT) {
      expect(elapsed).toBeLessThan(1000);
    }
  }
  if (process.env.APGAR_PERF_AGENT) {
    const ordered = [...samples].sort((left, right) => left - right);
    const median = ordered[Math.floor(ordered.length / 2)] ?? 0;
    console.log(`median_ms=${median} ${labeled.join(" ")}`);
  }
});

test("Focus visibility", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByTestId("page-agents")).toBeVisible();
  for (let i = 0; i < 20; i += 1) {
    const focused = await page.evaluate(() => document.activeElement?.getAttribute("data-testid"));
    if (focused === "nav-settings") {
      break;
    }
    await page.keyboard.press("Tab");
  }
  await expect(page.getByTestId("nav-settings")).toBeFocused();
  const style = await page.getByTestId("nav-settings").evaluate((el) => {
    const computed = getComputedStyle(el);
    return { outlineStyle: computed.outlineStyle, outlineWidth: computed.outlineWidth };
  });
  expect(style.outlineStyle).not.toBe("none");
  expect(style.outlineWidth).toBe("2px");
});

test("Dialog keyboard", async ({ page }) => {
  await page.goto("/agents/billing-copilot/releases/fp-8e2f0c6a1b93");
  const button = page.getByTestId("action-expected");
  await button.focus();
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("expected-metric-tool_error_rate")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("expected-metric-tool_error_rate")).toHaveCount(0);
  await expect(button).toBeFocused();
});
