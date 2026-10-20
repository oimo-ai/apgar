import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";

import { apiFetch, navigation } from "@/api/client";
import {
  bindSessionCache,
  useAgent,
  useAgentReleases,
  useAgents,
  useConnections,
  useEvaluations,
  useEvents,
  useIngestTokens,
  useInvalidate,
  useNotifications,
  usePost,
  useRelease,
  useSession,
  useSettings,
  useStatus,
} from "@/api/queries";

function freshClient(): QueryClient {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } });
}

function wrap(queryClient: QueryClient) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
  };
}

type Refetch = (query: { state: { data?: { final?: boolean } } }) => number | false;

function interval(queryClient: QueryClient, queryKey: readonly unknown[]): unknown {
  const query = queryClient.getQueryCache().find({ queryKey });
  const watched = query as { observers?: { options?: { refetchInterval?: unknown } }[] } | undefined;
  return watched?.observers?.[0]?.options?.refetchInterval;
}

function asRefetch(value: unknown): Refetch {
  if (typeof value !== "function") {
    throw new Error("expected a refetch interval");
  }
  return value as Refetch;
}

describe("queries", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn().mockImplementation(() => Promise.resolve(new Response("{}", { status: 200 }))));
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("clears the session cache once when the session is cleared", async () => {
    const queryClient = freshClient();
    const remove = vi.spyOn(queryClient, "removeQueries");
    bindSessionCache(queryClient);
    bindSessionCache(queryClient);
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("{}", { status: 401 })));
    vi.spyOn(navigation, "assign").mockImplementation(() => undefined);
    vi.spyOn(navigation, "currentPath").mockReturnValue("/");
    await expect(apiFetch("/api/v1/status")).rejects.toMatchObject({ status: 401 });
    expect(remove).toHaveBeenCalledTimes(1);
    expect(remove).toHaveBeenCalledWith({ queryKey: ["session"] });
  });

  it("requests each resource and skips a query with a blank id", async () => {
    const queryClient = freshClient();
    const wrapper = wrap(queryClient);
    renderHook(() => useStatus(), { wrapper });
    renderHook(() => useSession(), { wrapper });
    renderHook(() => useAgents(true), { wrapper });
    renderHook(() => useAgent("billing copilot"), { wrapper });
    renderHook(() => useAgentReleases("billing copilot"), { wrapper });
    renderHook(() => useRelease("billing copilot", "rel 1"), { wrapper });
    renderHook(() => useEvaluations("a", "live", false, true), { wrapper });
    renderHook(() => useEvents("a", "live", false, true), { wrapper });
    renderHook(() => useNotifications("failed", 20, 40), { wrapper });
    renderHook(() => useNotifications("all", 10, 0), { wrapper });
    renderHook(() => useConnections(), { wrapper });
    renderHook(() => useIngestTokens(), { wrapper });
    renderHook(() => useSettings(), { wrapper });
    const idle = freshClient();
    renderHook(() => useAgent(""), { wrapper: wrap(idle) });
    renderHook(() => useAgentReleases(""), { wrapper: wrap(idle) });
    renderHook(() => useRelease("", "rel"), { wrapper: wrap(idle) });
    renderHook(() => useEvaluations("", "", true), { wrapper: wrap(idle) });
    renderHook(() => useEvents("a", ""), { wrapper: wrap(idle) });

    await waitFor(() => {
      const urls = vi.mocked(fetch).mock.calls.map((call) => String(call[0]));
      expect(urls).toEqual(
        expect.arrayContaining([
          "/api/v1/status",
          "/api/v1/auth/session",
          "/api/v1/agents?limit=500",
          "/api/v1/agents/billing%20copilot",
          "/api/v1/agents/billing%20copilot/releases?limit=500",
          "/api/v1/agents/billing%20copilot/releases/rel%201",
          "/api/v1/agents/a/releases/live/evaluations?limit=500",
          "/api/v1/agents/a/releases/live/events",
          "/api/v1/notifications?status=failed&limit=20&offset=40",
          "/api/v1/notifications?limit=10&offset=0",
          "/api/v1/connections?limit=500",
          "/api/v1/ingest-tokens?limit=500",
          "/api/v1/settings",
        ]),
      );
    });
    expect(vi.mocked(fetch).mock.calls.map((call) => String(call[0])).some((url) => url.endsWith("/agents/"))).toBe(false);
    expect(interval(queryClient, ["status"])).toBe(10_000);
    expect(interval(queryClient, ["agents"])).toBe(5_000);
    expect(interval(queryClient, ["evaluations", "a", "live"])).toBe(60_000);
    expect(interval(queryClient, ["events", "a", "live"])).toBe(60_000);
  });

  it("polls a queued or open release and stops when it is final", () => {
    const queued = freshClient();
    renderHook(() => useRelease("a", "queued", true), { wrapper: wrap(queued) });
    renderHook(() => useEvaluations("a", "queued", true), { wrapper: wrap(queued) });
    renderHook(() => useEvents("a", "queued", true), { wrapper: wrap(queued) });
    expect(asRefetch(interval(queued, ["release", "a", "queued"]))({ state: { data: undefined } })).toBe(2_000);
    expect(interval(queued, ["evaluations", "a", "queued"])).toBe(2_000);
    expect(interval(queued, ["events", "a", "queued"])).toBe(2_000);

    const open = freshClient();
    renderHook(() => useRelease("a", "open"), { wrapper: wrap(open) });
    renderHook(() => useEvaluations("a", "open"), { wrapper: wrap(open) });
    renderHook(() => useEvents("a", "open"), { wrapper: wrap(open) });
    renderHook(() => useAgents(false), { wrapper: wrap(open) });
    const openInterval = asRefetch(interval(open, ["release", "a", "open"]));
    expect(openInterval({ state: { data: { final: false } } })).toBe(15_000);
    expect(openInterval({ state: { data: { final: true } } })).toBe(false);
    expect(openInterval({ state: { data: undefined } })).toBe(false);
    expect(interval(open, ["evaluations", "a", "open"])).toBe(false);
    expect(interval(open, ["events", "a", "open"])).toBe(false);
    expect(interval(open, ["agents"])).toBe(30_000);
  });

  it("invalidates the given keys and posts with or without a body", async () => {
    const queryClient = freshClient();
    const invalidate = vi.spyOn(queryClient, "invalidateQueries").mockResolvedValue();
    const { result: keys } = renderHook(() => useInvalidate(), { wrapper: wrap(queryClient) });
    await keys.current([["agents"], ["status"]]);
    expect(invalidate).toHaveBeenCalledTimes(2);

    const { result } = renderHook(() => usePost("/api/v1/demo/seed"), { wrapper: wrap(queryClient) });
    await result.current.mutateAsync({ days: 1 });
    await result.current.mutateAsync(undefined);
    const bodies = vi.mocked(fetch).mock.calls.map((call) => (call[1] as RequestInit).body);
    expect(bodies).toEqual(['{"days":1}', undefined]);
  });
});
