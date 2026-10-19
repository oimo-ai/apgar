import fs from "node:fs";
import path from "node:path";

import { request, type FullConfig } from "@playwright/test";

import { purgeDemo } from "./helpers";

async function waitFor(check: () => Promise<boolean>, timeoutMs: number, label: string): Promise<void> {
  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    if (await check()) {
      return;
    }
    await new Promise((resolve) => setTimeout(resolve, 2_000));
  }
  throw new Error(`timed out waiting for ${label}`);
}

export default async function globalSetup(config: FullConfig): Promise<void> {
  const baseURL = process.env.APGAR_UI_URL ?? "http://localhost:8080";
  const token = process.env.APGAR_ADMIN_TOKEN;
  if (!token) {
    throw new Error("APGAR_ADMIN_TOKEN is required");
  }
  const root = config.configFile ? path.dirname(config.configFile) : process.cwd();
  const authDir = path.join(root, "e2e/.auth");
  const stateDir = path.join(root, "e2e/.state");
  fs.mkdirSync(authDir, { recursive: true });
  fs.mkdirSync(stateDir, { recursive: true });
  const headers = { Authorization: `Bearer ${token}`, Accept: "application/json" };
  const api = await request.newContext({ baseURL });
  await waitFor(async () => (await api.get("/readyz")).ok(), 120_000, "readyz");
  if (process.env.APGAR_PERF_AGENT) {
    const loginOnly = await api.post("/api/v1/auth/login", { data: { token } });
    if (!loginOnly.ok()) {
      throw new Error(`login failed: ${loginOnly.status()}`);
    }
    await api.storageState({ path: path.join(authDir, "admin.json") });
    fs.writeFileSync(path.join(stateDir, "seeded.json"), JSON.stringify({ seeded: false, perf: true }));
    await api.dispose();
    return;
  }
  const login = await api.post("/api/v1/auth/login", { data: { token } });
  if (!login.ok()) {
    throw new Error(`login failed: ${login.status()}`);
  }
  await api.storageState({ path: path.join(authDir, "admin.json") });

  const listed = await api.get("/api/v1/agents?limit=500", { headers });
  const agents = (await listed.json()) as { items: { name: string }[] };
  const hasBilling = agents.items.some((item) => item.name === "billing-copilot");
  let stopped = false;
  if (hasBilling) {
    for (const target of ["billing-copilot/releases/fp-c4b2a9e8d711", "support-agent/releases/d4e5f6a"]) {
      const release = await api.get(`/api/v1/agents/${target}`, { headers });
      if (release.ok()) {
        const detail = (await release.json()) as { user_state?: { stopped_at?: string | null } };
        stopped ||= detail.user_state?.stopped_at != null;
      }
    }
  }
  if (!hasBilling || stopped) {
    if (hasBilling) {
      purgeDemo(root);
    }
    await api.post("/api/v1/demo/seed", { headers });
  }
  await waitFor(async () => {
    const status = await api.get("/api/v1/status", { headers });
    const body = (await status.json()) as { demo_seeding?: boolean };
    if (body.demo_seeding) {
      return false;
    }
    const release = await api.get("/api/v1/agents/support-agent/releases/b7c6d5e", { headers });
    if (!release.ok()) {
      return false;
    }
    const detail = (await release.json()) as { verdict_updated_at?: string | null };
    return detail.verdict_updated_at != null;
  }, 8 * 60_000, "demo verdicts");
  fs.writeFileSync(path.join(stateDir, "seeded.json"), JSON.stringify({ seeded: true }));
  await api.dispose();
}
