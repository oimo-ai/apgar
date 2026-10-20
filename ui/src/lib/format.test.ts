import {
  formatCi,
  formatPp,
  formatRate,
  formatRel,
  formatRelative,
  formatTolerance,
  formatUtcShort,
  formatValue,
  releaseHref,
} from "@/lib/format";

const MINUS = "\u2212";

describe("format", () => {
  it("formats relative times compactly and switches to a UTC date after a week", () => {
    const now = Date.parse("2026-10-12T12:00:00.000Z");
    const ago = (seconds: number) => new Date(now - seconds * 1000).toISOString();
    expect(formatRelative(ago(30), now)).toBe("just now");
    expect(formatRelative(ago(12 * 60), now)).toBe("12m ago");
    expect(formatRelative(ago(5 * 3600 + 50 * 60), now)).toBe("5h ago");
    expect(formatRelative(ago(36 * 3600), now)).toBe("1d ago");
    expect(formatRelative("2026-10-03T08:00:00.000Z", now)).toBe("Oct 3");
    expect(formatRelative("2025-12-30T08:00:00.000Z", now)).toBe("Dec 30, 2025");
  });

  it("formats a percentage point delta and ignores a bad timestamp", () => {
    expect(formatPp(0.02)).toBe("+2.0 pp");
    expect(formatPp(0)).toBe("0.0 pp");
    expect(formatRelative("not-a-date", Date.parse("2026-10-12T12:00:00.000Z"))).toBe("");
    expect(formatUtcShort("not-a-date")).toBe("not-a-date");
    expect(releaseHref("billing copilot", "rel/1")).toBe("/agents/billing%20copilot/releases/rel%2F1");
  });

  it("formats a short UTC timestamp", () => {
    const now = Date.parse("2026-10-12T12:00:00.000Z");
    expect(formatUtcShort("2026-10-10T18:42:53.601Z", now)).toBe("Oct 10, 18:42");
    expect(formatUtcShort("2025-01-05T03:07:00.000Z", now)).toBe("Jan 5, 2025, 03:07");
    expect(formatUtcShort(null, now)).toBe("n/a");
  });

  it("formats rates, including small values, zero, and null", () => {
    expect(formatRate(0.018)).toBe("1.8%");
    expect(formatRate(0.005)).toBe("0.50%");
    expect(formatRate(0)).toBe("0.0%");
    expect(formatRate(-0.004)).toBe(`${MINUS}0.40%`);
    expect(formatRate(null)).toBe("n/a");
  });

  it("uses U+2212 for negative deltas", () => {
    expect(formatPp(0.058)).toBe("+5.8 pp");
    expect(formatPp(-0.035)).toBe(`${MINUS}3.5 pp`);
    expect(formatPp(0)).toBe("0.0 pp");
    expect(formatPp(null)).toBe("n/a");
    expect(formatRel(0.1)).toBe("+10%");
    expect(formatRel(-0.35)).toBe(`${MINUS}35%`);
    expect(formatRel(0)).toBe("0%");
  });

  it("formats tolerances for the three directions", () => {
    expect(formatTolerance("abs", "up", 0.02)).toBe("+2 pp");
    expect(formatTolerance("abs", "down", 0.02)).toBe(`${MINUS}2 pp`);
    expect(formatTolerance("rel", "up", 0.15)).toBe("+15%");
    expect(formatTolerance("rel", "down", 0.15)).toBe(`${MINUS}15%`);
    expect(formatTolerance("rel", "both", 0.25)).toBe("±25%");
  });

  it("formats intervals", () => {
    expect(formatCi([0.058, 0.089], "abs")).toBe("+5.8 to +8.9 pp");
    expect(formatCi([-0.41, -0.29], "rel")).toBe(`${MINUS}41% to ${MINUS}29%`);
  });

  it("formats values by unit", () => {
    expect(formatValue(0.018, "rate")).toBe("1.8%");
    expect(formatValue(1.5, "count")).toBe("1.50");
    expect(formatValue(1842, "tokens")).toBe("1,842");
    expect(formatValue(240, "ms")).toBe("240 ms");
    expect(formatValue(10500, "ms")).toBe("10.5 s");
    expect(formatValue(0.0123, "usd")).toBe("$0.0123");
    expect(formatValue(null, "rate")).toBe("n/a");
  });
});
