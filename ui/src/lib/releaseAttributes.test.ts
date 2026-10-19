import { releaseChoice, releaseValue } from "@/lib/releaseAttributes";

describe("releaseChoice", () => {
  it("selects a known attribute directly", () => {
    expect(releaseChoice("gen_ai.agent.version")).toEqual({ choice: "gen_ai.agent.version", custom: "" });
  });

  it("falls back to custom for unknown attributes", () => {
    expect(releaseChoice("my.release")).toEqual({ choice: "custom", custom: "my.release" });
    expect(releaseChoice("custom")).toEqual({ choice: "custom", custom: "custom" });
  });

  it("leaves nothing selected when unset", () => {
    expect(releaseChoice("")).toEqual({ choice: "", custom: "" });
  });
});

describe("releaseValue", () => {
  it("uses the trimmed custom input only for the custom choice", () => {
    expect(releaseValue("custom", "  my.release ")).toBe("my.release");
    expect(releaseValue("apgar.release", "ignored")).toBe("apgar.release");
  });
});
