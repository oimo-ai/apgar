import type { ReleaseDetail } from "@/api/types";
import { formatCount } from "@/lib/format";
import { type LabelTone, releaseLabel } from "@/lib/releaseLabel";

export type StatusKind =
  | "regression"
  | "healthy"
  | "possible_regression"
  | "looks_healthy"
  | "not_enough_data"
  | "unconfirmed"
  | "collecting"
  | "waiting"
  | "first_release";

export type PhaseKind = "monitoring" | "stopping" | "ended" | "stopped" | "replaced";

export type ReleaseStatus = {
  kind: StatusKind;
  tone: LabelTone;
  title: string;
  note: string | null;
  phase: { kind: PhaseKind; label: string; by?: string };
};

function phaseOf(detail: ReleaseDetail): ReleaseStatus["phase"] {
  if (detail.final) {
    const ended = detail.summary?.ended;
    if (ended?.reason === "superseded" && ended.by) {
      return { kind: "replaced", label: "Replaced by", by: ended.by };
    }
    return ended?.reason === "stopped" ? { kind: "stopped", label: "Stopped" } : { kind: "ended", label: "Ended" };
  }
  return detail.user_state.stopped_at ? { kind: "stopping", label: "Stopping" } : { kind: "monitoring", label: "Monitoring" };
}

function describe(detail: ReleaseDetail): Pick<ReleaseStatus, "kind" | "note"> {
  const evaluation = detail.evaluation;
  if (detail.state === "FAIL") {
    return { kind: "regression", note: detail.early ? "Confirmed early, before the full sample was in." : null };
  }
  if (detail.state === "PASS") {
    return { kind: "healthy", note: detail.final ? null : "A regression found before monitoring ends can still change this." };
  }
  if (detail.final) {
    return {
      kind: "unconfirmed",
      note: "No regression was found, but monitoring ended before there was enough data to confirm it healthy.",
    };
  }
  if (detail.reason === "no_baseline") {
    return { kind: "first_release", note: "Nothing to compare yet; it becomes the baseline for the next release." };
  }
  if (evaluation === null) {
    return { kind: "waiting", note: "Waiting for the first check." };
  }
  if (detail.state === "PENDING") {
    return {
      kind: "collecting",
      note:
        detail.reason === "insufficient_baseline"
          ? "The baseline does not have enough turns or sessions yet."
          : "No verdict until the full sample is in, unless a strong regression shows up first.",
    };
  }
  if (detail.reason === "fail_candidate") {
    return {
      kind: "possible_regression",
      note: detail.early
        ? `Seen early, after ${formatCount(evaluation.n_candidate_turns)} turns; the next check confirms or clears it.`
        : "The next check confirms or clears it.",
    };
  }
  if (detail.reason === "pass_candidate") {
    return { kind: "looks_healthy", note: "No regression so far; the next check confirms it." };
  }
  return { kind: "not_enough_data", note: "No regression so far, but small changes would not show yet." };
}

export function checkKind(row: { state: string; reason: string | null | undefined; final?: boolean }): Exclude<StatusKind, "waiting"> {
  if (row.state === "FAIL") {
    return "regression";
  }
  if (row.state === "PASS") {
    return "healthy";
  }
  if (row.final) {
    return "unconfirmed";
  }
  if (row.reason === "no_baseline") {
    return "first_release";
  }
  if (row.state === "PENDING") {
    return "collecting";
  }
  if (row.reason === "fail_candidate") {
    return "possible_regression";
  }
  return row.reason === "pass_candidate" ? "looks_healthy" : "not_enough_data";
}

export function releaseStatus(detail: ReleaseDetail): ReleaseStatus {
  const { label, tone } = releaseLabel({ ...detail, early: false });
  return { ...describe(detail), title: label, tone, phase: phaseOf(detail) };
}
