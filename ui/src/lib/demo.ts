import { apiFetch } from "@/api/client";
import type { AgentOut, Page, ReleaseOut } from "@/api/types";

export function demoAgentNames(agents: AgentOut[]): string[] {
  return agents
    .filter((agent) => agent.is_demo)
    .map((agent) => agent.name)
    .sort();
}

// The release a new user lands on after loading the demo: the newest
// regression of the first of the given agents that has one. Only a final one
// counts, so the page it opens no longer changes while the demo loads.
export async function findDemoRegression(names: string[]): Promise<ReleaseOut | null> {
  for (const name of names) {
    const releases = await apiFetch<Page<ReleaseOut>>(`/api/v1/agents/${encodeURIComponent(name)}/releases?limit=500`);
    const failed = releases.items
      .filter((release) => release.state === "FAIL" && release.final)
      .sort((a, b) => b.first_seen.localeCompare(a.first_seen))[0];
    if (failed) {
      return failed;
    }
  }
  return null;
}
