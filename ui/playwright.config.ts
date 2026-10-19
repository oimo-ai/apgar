import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "e2e",
  globalSetup: "./e2e/global-setup.ts",
  timeout: 60_000,
  expect: { timeout: 10_000 },
  retries: 1,
  fullyParallel: false,
  workers: 1,
  reporter: [["list"], ["html", { open: "never" }]],
  use: {
    baseURL: process.env.APGAR_UI_URL ?? "http://localhost:8080",
    storageState: "e2e/.auth/admin.json",
  },
  projects: [
    {
      name: "login",
      testMatch: /login\.spec\.ts/,
      use: { ...devices["Desktop Chrome"], storageState: { cookies: [], origins: [] } },
    },
    {
      name: "chromium",
      testIgnore: [/login\.spec\.ts/, /release\.spec\.ts/, /zz-empty-state\.spec\.ts/, /actions\.spec\.ts/, /smoke\.spec\.ts/],
      dependencies: ["login"],
      use: { ...devices["Desktop Chrome"] },
    },
    {
      name: "mutations",
      testMatch: /release\.spec\.ts/,
      dependencies: ["chromium"],
      use: { ...devices["Desktop Chrome"] },
    },
    {
      name: "actions",
      testMatch: /actions\.spec\.ts/,
      dependencies: ["mutations"],
      use: { ...devices["Desktop Chrome"] },
    },
    {
      name: "empty",
      testMatch: /zz-empty-state\.spec\.ts/,
      dependencies: ["actions"],
      use: { ...devices["Desktop Chrome"] },
    },
    {
      name: "smoke",
      testMatch: /smoke\.spec\.ts/,
      use: { ...devices["Desktop Chrome"], storageState: { cookies: [], origins: [] } },
    },
  ],
});
