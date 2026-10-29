import { apiFetch } from "@/api/client";
import type { AgentOut } from "@/api/types";
import { demoAgentNames, findDemoRegression } from "@/lib/demo";

vi.mock("@/api/client", () => ({
  apiFetch: vi.fn(),
}));

function page<T>(items: T[]) {
  return { items, total: items.length, limit: 500, offset: 0 };
}

type Row = { agent: string; release: string; state: string; final: boolean; first_seen: string };

const RELEASES: Record<string, Row[]> = {
  "/api/v1/agents/a-healthy/releases?limit=500": [
    { agent: "a-healthy", release: "r1", state: "PASS", final: true, first_seen: "2026-10-01T00:00:00Z" },
  ],
  "/api/v1/agents/billing-copilot/releases?limit=500": [
    { agent: "billing-copilot", release: "old", state: "FAIL", final: true, first_seen: "2026-10-01T00:00:00Z" },
    { agent: "billing-copilot", release: "new", state: "FAIL", final: true, first_seen: "2026-10-05T00:00:00Z" },
    { agent: "billing-copilot", release: "ok", state: "PASS", final: true, first_seen: "2026-10-06T00:00:00Z" },
  ],
};

describe("demoAgentNames", () => {
  it("keeps demo agents sorted by name", () => {
    const agents = [
      { name: "support-agent", is_demo: true },
      { name: "mine", is_demo: false },
      { name: "billing-copilot", is_demo: true },
    ] as AgentOut[];
    expect(demoAgentNames(agents)).toEqual(["billing-copilot", "support-agent"]);
  });
});

describe("findDemoRegression", () => {
  beforeEach(() => {
    vi.mocked(apiFetch).mockReset();
    vi.mocked(apiFetch).mockImplementation((path: string) => Promise.resolve(page(RELEASES[path] ?? [])));
  });

  it("returns the newest regression of the first agent that has one", async () => {
    const release = await findDemoRegression(["a-healthy", "billing-copilot", "support-agent"]);
    expect(release?.agent).toBe("billing-copilot");
    expect(release?.release).toBe("new");
    expect(apiFetch).not.toHaveBeenCalledWith("/api/v1/agents/support-agent/releases?limit=500");
  });

  it("skips a regression whose monitoring is still open", async () => {
    const releases: Row[] = [
      { agent: "billing-copilot", release: "settled", state: "FAIL", final: true, first_seen: "2026-10-01T00:00:00Z" },
      { agent: "billing-copilot", release: "open", state: "FAIL", final: false, first_seen: "2026-10-05T00:00:00Z" },
    ];
    vi.mocked(apiFetch).mockImplementation(() => Promise.resolve(page(releases)));
    expect((await findDemoRegression(["billing-copilot"]))?.release).toBe("settled");
    releases.splice(0, 1);
    expect(await findDemoRegression(["billing-copilot"])).toBeNull();
  });

  it("returns null when no agent failed", async () => {
    expect(await findDemoRegression(["a-healthy"])).toBeNull();
    expect(await findDemoRegression([])).toBeNull();
  });
});
