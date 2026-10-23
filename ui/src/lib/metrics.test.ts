import { naReasonLabel, reasonLabel, sliceReasonLabel, unavailableReason } from "@/lib/metrics";

describe("metric reasons", () => {
  it("labels a known reason and spaces an unknown one", () => {
    expect(reasonLabel(null)).toBe("");
    expect(reasonLabel("fail_candidate")).toBe("fail candidate");
    expect(reasonLabel("custom_reason")).toBe("custom reason");
  });

  it("labels why a metric is not applicable", () => {
    expect(naReasonLabel(undefined)).toBe("n/a");
    expect(naReasonLabel("no_cost")).toBe("Too few turns have a cost");
    expect(naReasonLabel("custom")).toBe("custom");
  });

  it("words an unavailable metric from the missing input or the reason", () => {
    expect(unavailableReason("tool arguments", "coverage")).toBe("missing tool arguments");
    expect(unavailableReason(null, "no_tools")).toBe("no tool calls in the previous release");
    expect(unavailableReason(undefined, "disabled")).toBe("turned off for this agent");
  });

  it("labels why a slice was skipped", () => {
    expect(sliceReasonLabel(null)).toBe("Not enough data to compare");
    expect(sliceReasonLabel("zero_baseline")).toBe("Previous value is 0, so a relative change is undefined");
    expect(sliceReasonLabel("coverage")).toBe("Too few turns or tool calls carry the needed input");
    expect(sliceReasonLabel("custom_reason")).toBe("custom reason");
  });
});
