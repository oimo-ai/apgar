import type { EvaluationOut, ReleaseDetail, VerdictSettings } from "@/api/types";
import { type LabelTone, releaseLabel } from "@/lib/releaseLabel";

export type VerdictSummary = {
  tone: LabelTone;
  label: string;
  confirmations: { done: number; needed: number } | null;
  collecting: boolean;
};

export function formatDuration(seconds: number): string {
  const minutes = Math.max(0, Math.floor(seconds / 60));
  return minutes < 60 ? `${minutes} min` : `${Math.round(minutes / 60)} h`;
}

export function formatUntil(iso: string | null | undefined, now = Date.now()): string | null {
  const at = iso ? Date.parse(iso) : Number.NaN;
  if (Number.isNaN(at)) {
    return null;
  }
  const minutes = Math.round((at - now) / 60_000);
  if (minutes < -1) {
    return "overdue";
  }
  return minutes < 1 ? "in under a minute" : `in ${formatDuration(minutes * 60)}`;
}

export function confirmationsSoFar(history: EvaluationOut[], reason: string, changedAt: string | null = null): number {
  const since = changedAt ? Date.parse(changedAt) : null;
  const baseline = history[0]?.baseline_release;
  let count = 0;
  for (const row of history) {
    if (row.reason !== reason || row.baseline_release !== baseline || (since !== null && Date.parse(row.evaluated_at) <= since)) {
      break;
    }
    count += 1;
  }
  return count;
}

export function verdictSummary(detail: ReleaseDetail, settings: VerdictSettings | undefined, history: EvaluationOut[] = []): VerdictSummary {
  const { label, tone } = releaseLabel(detail);
  const base: VerdictSummary = {
    tone,
    label,
    confirmations: null,
    collecting: false,
  };

  if (detail.state === "FAIL" || detail.state === "PASS" || detail.final || detail.evaluation === null) {
    return base;
  }
  if (detail.state === "PENDING") {
    return { ...base, collecting: detail.reason !== "no_baseline" };
  }
  if (detail.reason === "fail_candidate") {
    return {
      ...base,
      confirmations: { done: confirmationsSoFar(history, "fail_candidate", detail.user_state.changed_at), needed: settings?.fail_confirmations ?? 2 },
    };
  }
  return {
    ...base,
    confirmations:
      detail.reason === "pass_candidate"
        ? { done: confirmationsSoFar(history, "pass_candidate", detail.user_state.changed_at), needed: settings?.pass_confirmations ?? 2 }
        : null,
  };
}
