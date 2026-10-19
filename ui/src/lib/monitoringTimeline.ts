import type { EvaluationOut, ReleaseDetail, ReleaseEventOut } from "@/api/types";
import { formatCount, formatUtcShort } from "@/lib/format";
import { metricLabel } from "@/lib/metrics";
import { releaseLabel } from "@/lib/releaseLabel";
import { checkKind, type StatusKind } from "@/lib/releaseStatus";
import { formatDuration, formatUntil } from "@/lib/verdictSummary";

export type SegmentKind = Exclude<StatusKind, "waiting">;

export type Fact = { label: string; value: string; mono?: boolean };

export type TipContent = { title: string; meaning?: string; facts: Fact[]; notes: string[] };

export type Segment = {
  kind: SegmentKind;
  from: number;
  to: number;
  checks: number;
  stale: boolean;
  tip: TipContent;
};

export type MarkerKind = "baseline" | "expected" | "stop" | "end" | "now";

export type Marker = { kind: MarkerKind; at: number; tip: TipContent };

export type Timeline = {
  start: number;
  cap: number;
  end: number;
  live: boolean;
  idle: boolean;
  segments: Segment[];
  markers: Marker[];
  rest: TipContent | null;
};

export type Span = { from: number; to: number };

export type Box = Span & { x: number; width: number };

export const SEGMENT_MEANING: Record<SegmentKind, string> = {
  regression: "A regression was confirmed.",
  possible_regression: "A metric looked worse; the next check confirms or clears it.",
  healthy: "Every metric was confirmed within tolerance.",
  looks_healthy: "No regression; the next check confirms it healthy.",
  not_enough_data: "No regression, but small changes would not show yet.",
  unconfirmed: "Monitoring ended before it could be confirmed healthy.",
  collecting: "Collecting traffic before a verdict is possible.",
  first_release: "Nothing to compare yet.",
};

const IDLE_AFTER_MS = 24 * 3600_000;
const QUIET_GAP_MS = 6 * 3600_000;

const UTC = (iso: string, now: number) => `${formatUtcShort(iso, now)} UTC`;

function checkFacts(run: EvaluationOut[], now: number): Fact[] {
  const first = run[0];
  const last = run[run.length - 1];
  const manual = run.filter((row) => row.manual).length;
  let count = formatCount(run.length);
  if (manual > 0) {
    count += manual === run.length ? ", manual" : `, ${formatCount(manual)} manual`;
  }
  const facts: Fact[] = [{ label: "Checks", value: count }];
  if (run.length === 1) {
    facts.push({ label: "At", value: UTC(first.evaluated_at, now) });
  } else {
    facts.push({ label: "From", value: UTC(first.evaluated_at, now) }, { label: "To", value: UTC(last.evaluated_at, now) });
  }
  if (first.baseline_release) {
    facts.push({ label: "Baseline", value: first.baseline_release, mono: true });
  }
  return facts;
}

function segmentTip(kind: SegmentKind, run: EvaluationOut[], stale: boolean, until: number, now: number): TipContent {
  const notes: string[] = [];
  const quiet = until - Date.parse(run[run.length - 1].evaluated_at);
  if (quiet > QUIET_GAP_MS) {
    notes.push(`No checks for ${formatDuration(quiet / 1000)} after this. Checks pause when no new turns arrive.`);
  }
  if (stale) {
    notes.push("Before the last change, so it no longer counts toward confirmation.");
  }
  return {
    title: releaseLabel({ ...run[0], early: false }).label,
    meaning: SEGMENT_MEANING[kind],
    facts: checkFacts(run, now),
    notes,
  };
}

function endTitle(detail: ReleaseDetail): string {
  const ended = detail.summary?.ended;
  if (ended?.reason === "superseded") {
    return ended.by ? `Replaced by ${ended.by}` : "Replaced by a newer release";
  }
  return ended?.reason === "stopped" ? "Monitoring stopped" : "Monitoring window ended";
}

function eventMarker(row: ReleaseEventOut, at: number, ended: boolean, checks: EvaluationOut[], now: number): Marker | null {
  const ts = Date.parse(row.ts);
  const when: Fact = { label: "When", value: UTC(row.ts, now) };
  const by: Fact[] = row.actor ? [{ label: "By", value: row.actor }] : [];
  const effect = ended ? "After monitoring ended." : "Confirmation started over.";
  if (row.type === "manual_baseline") {
    const release = typeof row.payload.release === "string" ? row.payload.release : null;
    const before = [...checks].reverse().find((check) => Date.parse(check.evaluated_at) < ts)?.baseline_release;
    const facts: Fact[] = release ? [{ label: "To", value: release, mono: true }] : [];
    if (before && before !== release) {
      facts.push({ label: "Before", value: before, mono: true });
    }
    facts.push(when, ...by);
    return { kind: "baseline", at, tip: { title: release ? "Baseline changed" : "Baseline set to automatic", facts, notes: [effect] } };
  }
  if (row.type === "expected_changes") {
    const metrics = Array.isArray(row.payload.metrics) ? (row.payload.metrics as string[]) : [];
    const named = metrics.length === 0 ? "None" : metrics.map((id) => metricLabel(id)).join(", ");
    return {
      kind: "expected",
      at,
      tip: { title: "Expected changes updated", facts: [{ label: "Metrics", value: named }, when, ...by], notes: [effect] },
    };
  }
  if (row.type === "stop") {
    return {
      kind: "stop",
      at,
      tip: { title: "Stop requested", facts: [when, ...by], notes: ["The final check uses traffic up to this point."] },
    };
  }
  return null;
}

export function buildTimeline(detail: ReleaseDetail, history: EvaluationOut[], events: ReleaseEventOut[], now: number): Timeline {
  const start = Date.parse(detail.first_seen);
  const cap = Math.max(start + 1, Date.parse(detail.max_window_end));
  const stopped = detail.user_state.stopped_at ? Date.parse(detail.user_state.stopped_at) : null;
  const finalEnd = Date.parse(detail.evaluation?.window_end ?? detail.final_at ?? detail.max_window_end);
  const end = Math.max(start, detail.final ? Math.min(finalEnd, cap) : Math.min(now, stopped ?? cap, cap));
  const clamp = (ts: number) => Math.min(Math.max(ts, start), end);
  const changed = detail.user_state.changed_at ? Date.parse(detail.user_state.changed_at) : null;
  const changedAt = changed !== null && changed <= end ? changed : null;
  const idle = !detail.final && detail.last_seen !== null && Date.parse(detail.last_seen) < now - IDLE_AFTER_MS;
  const checks = [...history].sort((left, right) => Date.parse(left.evaluated_at) - Date.parse(right.evaluated_at));

  const runs: { kind: SegmentKind; stale: boolean; rows: EvaluationOut[] }[] = [];
  for (const row of checks) {
    const kind = checkKind(row);
    const stale = changedAt !== null && Date.parse(row.evaluated_at) <= changedAt;
    const last = runs[runs.length - 1];
    if (last && last.kind === kind && last.stale === stale && last.rows[0].baseline_release === row.baseline_release) {
      last.rows.push(row);
    } else {
      runs.push({ kind, stale, rows: [row] });
    }
  }

  const segments: Segment[] = [];
  const firstAt = runs.length > 0 ? clamp(Date.parse(runs[0].rows[0].evaluated_at)) : end;
  if (firstAt > start) {
    segments.push({
      kind: "collecting",
      from: start,
      to: firstAt,
      checks: 0,
      stale: false,
      tip: {
        title: "Collecting",
        meaning: runs.length > 0 ? "Traffic before the first check." : "Waiting for the first check.",
        facts: [{ label: "First seen", value: UTC(detail.first_seen, now) }],
        notes: [],
      },
    });
  }
  runs.forEach((run, index) => {
    const next = runs[index + 1];
    segments.push({
      kind: run.kind,
      from: clamp(Date.parse(run.rows[0].evaluated_at)),
      to: next ? clamp(Date.parse(next.rows[0].evaluated_at)) : end,
      checks: run.rows.length,
      stale: run.stale,
      tip: segmentTip(run.kind, run.rows, run.stale, next ? Date.parse(next.rows[0].evaluated_at) : end, now),
    });
  });

  const markers: Marker[] = [];
  const stopEnded = detail.final && detail.summary?.ended?.reason === "stopped";
  for (const row of events) {
    if (row.type === "stop" && stopEnded) {
      continue;
    }
    const ts = Date.parse(row.ts);
    const marker = eventMarker(row, clamp(ts), detail.final && ts > end, checks, now);
    if (marker) {
      markers.push(marker);
    }
  }
  if (detail.final) {
    markers.push({
      kind: "end",
      at: end,
      tip: {
        title: endTitle(detail),
        facts: [
          { label: "Ended", value: UTC(new Date(end).toISOString(), now) },
          { label: "Verdict", value: releaseLabel(detail).label },
        ],
        notes: [],
      },
    });
  } else {
    const next = formatUntil(detail.timing.next_check_at, now);
    markers.push({
      kind: "now",
      at: Math.min(now, cap),
      tip: {
        title: "Now",
        facts: !idle && next ? [{ label: "Next check", value: next }] : [],
        notes: idle ? ["No traffic for over 24 h, so checks are paused."] : [],
      },
    });
  }

  let rest: TipContent | null = null;
  if (end < cap) {
    const until = UTC(new Date(cap).toISOString(), now);
    rest =
      detail.final || stopped !== null
        ? {
            title: "Not monitored",
            meaning: "Monitoring ended before the window closed.",
            facts: [{ label: "Window end", value: until }],
            notes: [],
          }
        : {
            title: "Remaining window",
            meaning: "Monitoring runs until this time at the latest.",
            facts: [{ label: "Ends by", value: until }],
            notes: [],
          };
  }

  return { start, cap, end, live: !detail.final, idle, segments, markers, rest };
}

export function fitWidths(spans: Span[], total: number, min: number): number[] {
  const natural = spans.map((span) => Math.max(0, span.to - span.from));
  const floor = Math.min(min, total / Math.max(1, spans.length));
  const pinned = new Set<number>();
  for (;;) {
    const free = natural.reduce((sum, width, index) => (pinned.has(index) ? sum : sum + width), 0);
    const budget = total - floor * pinned.size;
    const loose = spans.length - pinned.size;
    const widths = natural.map((width, index) => {
      if (pinned.has(index)) {
        return floor;
      }
      return free > 0 ? (width / free) * budget : budget / loose;
    });
    const short = widths.flatMap((width, index) => (!pinned.has(index) && width < floor ? [index] : []));
    if (short.length === 0) {
      return widths;
    }
    short.forEach((index) => pinned.add(index));
  }
}

export function timeScale(spans: Span[], total: number, min: number): { boxes: Box[]; at: (ts: number) => number } {
  const widths = fitWidths(spans, total, min);
  let x = 0;
  const boxes = spans.map((span, index) => {
    const box = { ...span, x, width: widths[index] };
    x += widths[index];
    return box;
  });
  const at = (ts: number) => {
    for (let index = boxes.length - 1; index >= 0; index -= 1) {
      const box = boxes[index];
      if (ts >= box.from) {
        const length = box.to - box.from;
        return box.x + (length > 0 ? Math.min(1, (ts - box.from) / length) : 1) * box.width;
      }
    }
    return 0;
  };
  return { boxes, at };
}
