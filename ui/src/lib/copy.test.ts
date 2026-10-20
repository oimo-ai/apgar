import { copyText } from "@/lib/copy";

describe("copyText", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("uses the clipboard API", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText } });
    await copyText("apg_ing_token");
    expect(writeText).toHaveBeenCalledWith("apg_ing_token");
  });

  it("falls back when the clipboard API is missing or rejects", async () => {
    const exec = vi.fn().mockReturnValue(true);
    document.execCommand = exec;
    Object.defineProperty(navigator, "clipboard", { configurable: true, value: undefined });
    await copyText("plain");
    expect(exec).toHaveBeenCalledWith("copy");

    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText: vi.fn().mockRejectedValue(new Error("denied")) },
    });
    await copyText("again");
    expect(exec).toHaveBeenCalledTimes(2);
  });
});
