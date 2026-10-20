import { execFileSync } from "node:child_process";
import { resolve } from "node:path";

import { expect, type APIResponse, type Page } from "@playwright/test";

export function adminToken(): string {
  const token = process.env.APGAR_ADMIN_TOKEN;
  if (!token) {
    throw new Error("APGAR_ADMIN_TOKEN is required");
  }
  return token;
}

export function bearer(): { Authorization: string } {
  return { Authorization: `Bearer ${adminToken()}` };
}

export async function api(
  page: Page,
  path: string,
  init?: { method?: string; data?: unknown },
): Promise<APIResponse> {
  return page.request.fetch(path, {
    method: init?.method ?? "GET",
    headers: { ...bearer(), Accept: "application/json" },
    data: init?.data,
  });
}

const COMPOSE_DEV = ["compose", "-f", "docker-compose.yml", "-f", "docker-compose.dev.yml"];

export function purgeDemo(uiRoot: string): void {
  execFileSync("docker", [...COMPOSE_DEV, "run", "--rm", "--no-deps", "apgar-worker", "demo", "purge"], {
    cwd: resolve(uiRoot, ".."),
    stdio: "inherit",
  });
}

export async function gotoAndWait(page: Page, path: string, testid: string): Promise<void> {
  await page.goto(path);
  await expect(page.getByTestId(testid)).toBeVisible();
}
