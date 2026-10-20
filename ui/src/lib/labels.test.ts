import { productLabel, warningLabel } from "@/lib/labels";

describe("labels", () => {
  it("names a known product and keeps an unknown one", () => {
    expect(productLabel("langfuse")).toBe("Langfuse");
    expect(productLabel("custom")).toBe("custom");
  });

  it("names a known warning and spaces an unknown one", () => {
    expect(warningLabel("sync_error")).toBe("Langfuse sync failing");
    expect(warningLabel("late_share")).toBe("late share");
  });
});
