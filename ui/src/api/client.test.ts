import { apiFetch, navigation, onSessionCleared } from "@/api/client";

describe("apiFetch", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("sends X-Apgar-Request on POST and not on GET", async () => {
    const fetchMock = vi.fn().mockImplementation(() => Promise.resolve(new Response("{}", { status: 200 })));
    vi.stubGlobal("fetch", fetchMock);
    await apiFetch("/api/v1/agents");
    await apiFetch("/api/v1/agents", { method: "POST", body: "{}" });
    const getHeaders = fetchMock.mock.calls[0]?.[1].headers as Headers;
    const postHeaders = fetchMock.mock.calls[1]?.[1].headers as Headers;
    expect(getHeaders.get("X-Apgar-Request")).toBeNull();
    expect(postHeaders.get("X-Apgar-Request")).toBe("1");
    expect(postHeaders.get("Content-Type")).toBe("application/json");
  });

  it("redirects to login on 401 outside auth routes", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("{}", { status: 401 })));
    const assign = vi.spyOn(navigation, "assign").mockImplementation(() => undefined);
    vi.spyOn(navigation, "currentPath").mockReturnValue("/settings");
    await expect(apiFetch("/api/v1/agents")).rejects.toMatchObject({ status: 401, code: "unauthorized" });
    expect(assign).toHaveBeenCalledWith("/login?redirect=%2Fsettings");
  });

  it("parses the error body", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ error: { code: "not_found", message: "agent not found" } }), {
          status: 404,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );
    await expect(apiFetch("/api/v1/agents/missing")).rejects.toMatchObject({
      status: 404,
      code: "not_found",
      message: "agent not found",
    });
  });

  it("reads the current path and assigns through location", () => {
    window.history.pushState({}, "", "/settings?tab=agents");
    expect(navigation.currentPath()).toBe("/settings?tab=agents");
    navigation.assign("/login");
  });

  it("notifies session listeners and keeps a non-JSON error", async () => {
    const listener = vi.fn();
    const stop = onSessionCleared(listener);
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("nope", { status: 401 })));
    const assign = vi.spyOn(navigation, "assign").mockImplementation(() => undefined);
    vi.spyOn(navigation, "currentPath").mockReturnValue("/agents");
    await expect(apiFetch("/api/v1/agents")).rejects.toMatchObject({ status: 401 });
    expect(listener).toHaveBeenCalledOnce();
    expect(assign).toHaveBeenCalledWith("/login?redirect=%2Fagents");
    stop();

    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("nope", { status: 500, statusText: "boom" })));
    await expect(apiFetch("/api/v1/agents")).rejects.toMatchObject({ status: 500, code: "error", message: "boom" });
  });

  it("returns nothing for an empty body and for 204", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(null, { status: 204 })));
    await expect(apiFetch("/api/v1/agents/billing")).resolves.toBeUndefined();
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("", { status: 200 })));
    await expect(apiFetch("/api/v1/agents/billing")).resolves.toBeUndefined();
  });
});
