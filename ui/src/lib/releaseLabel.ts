export type LabelTone = "neutral" | "calm" | "warning" | "fail" | "pass";

export type ReleaseLike = {
  state: string;
  reason: string | null | undefined;
  final?: boolean;
  early?: boolean;
};

export function releaseLabel(release: ReleaseLike): { label: string; tone: LabelTone } {
  const { state, reason, final = false, early = false } = release;
  if (state === "FAIL") {
    return { label: "Regression", tone: "fail" };
  }
  if (state === "PASS") {
    return { label: "Healthy", tone: "pass" };
  }
  if (final) {
    return { label: "Unconfirmed", tone: "calm" };
  }
  if (reason === "no_baseline") {
    return { label: "First release", tone: "neutral" };
  }
  if (state === "PENDING") {
    return { label: "Collecting", tone: "neutral" };
  }
  if (reason === "fail_candidate") {
    return { label: early ? "Possible regression, early" : "Possible regression", tone: "warning" };
  }
  if (reason === "pass_candidate") {
    return { label: "Looks healthy", tone: "calm" };
  }
  return { label: "Not enough data", tone: "calm" };
}

export const TONE_PILL: Record<LabelTone, string> = {
  neutral: "",
  calm: "",
  warning: "bg-inconclusive-bg text-inconclusive",
  fail: "bg-fail-bg text-fail",
  pass: "bg-pass-bg text-pass",
};
