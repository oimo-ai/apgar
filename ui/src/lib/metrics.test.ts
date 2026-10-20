import { naReasonLabel, reasonLabel, sliceReasonLabel } from "@/lib/metrics";

describe("metric reasons", () => {
  it("labels a known reason and spaces an unknown one", () => {
    expect(reasonLabel(null)).toBe("");
    expect(reasonLabel("fail_candidate")).toBe("fail candidate");
    expect(reasonLabel("custom_reason")).toBe("custom reason");
  });

  it("labels why a metric is not applicable", () => {
    expect(naReasonLabel(undefined)).toBe("n/a");
    expect(naReasonLabel("no_cost")).toBe("Cost not available for enough turns");
    expect(naReasonLabel("custom")).toBe("custom");
  });

  it("labels why a slice was skipped", () => {
    expect(sliceReasonLabel(null)).toBe("Not enough data to compare");
    expect(sliceReasonLabel("zero_baseline")).toBe("Previous value is 0, so a relative change is undefined");
    expect(sliceReasonLabel("coverage")).toBe("Too few units carry the required input (below 90%)");
    expect(sliceReasonLabel("custom_reason")).toBe("custom reason");
  });
});
