import { readFileSync } from "node:fs";

import { expect, test } from "@playwright/test";

import { adminToken } from "./helpers";

const { version } = JSON.parse(readFileSync(new URL("../package.json", import.meta.url), "utf8")) as { version: string };

test("Unauthenticated redirect", async ({ page }) => {
  await page.goto("/");
  await expect(page).toHaveURL(/\/login\?redirect=%2F/);
  await expect(page.getByTestId("page-login")).toBeVisible();
});

test("Version and GitHub link", async ({ page }) => {
  await page.goto("/login");
  await expect(page.getByTestId("login-version")).toHaveText(`Self hosted · v${version}`);
  await expect(page.getByTestId("login-github")).toHaveAttribute("href", "https://github.com/oimo-ai/apgar");
});

test("Wrong token", async ({ page }) => {
  await page.goto("/login");
  await page.getByTestId("login-token").fill("wrong");
  await page.getByTestId("login-submit").click();
  await expect(page.getByTestId("login-error")).toHaveText("Invalid token");
  await expect(page).toHaveURL(/\/login/);
});

test("Successful login and persistence", async ({ page }) => {
  await page.goto("/login");
  await page.getByTestId("login-token").fill(adminToken());
  await page.getByTestId("login-submit").click();
  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByTestId("page-agents")).toBeVisible();
  await page.reload();
  await expect(page.getByTestId("page-agents")).toBeVisible();
});

test("Logout", async ({ page }) => {
  await page.goto("/login");
  await page.getByTestId("login-token").fill(adminToken());
  await page.getByTestId("login-submit").click();
  await expect(page.getByTestId("page-agents")).toBeVisible();
  await page.getByTestId("logout-button").click();
  await expect(page).toHaveURL(/\/login/);
  await page.goto("/");
  await expect(page).toHaveURL(/\/login/);
});
