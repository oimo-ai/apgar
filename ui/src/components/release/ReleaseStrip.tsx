import type { ReactNode } from "react";

import type { EvaluationOut, ReleaseDetail, ReleaseEventOut, VerdictSettings } from "@/api/types";
import { MonitoringTrack, spoken, TipBody } from "@/components/release/MonitoringTrack";
import { TimeAgo } from "@/components/TimeAgo";
import { ReasonTip, Tip } from "@/components/ui/tooltip";
import { formatCount, formatRelative, formatUtcShort } from "@/lib/format";
import { buildTimeline, type TipContent } from "@/lib/monitoringTimeline";
import { cn } from "@/lib/utils";
import { formatDuration, formatUntil, type VerdictSummary } from "@/lib/verdictSummary";

function share(value: number, total: number): number {
  return total > 0 ? Math.min(1, Math.max(0, value / total)) : 0;
}

function percent(value: number): string {
  return `${(value * 100).toFixed(2)}%`;
}

function Block({ testId, title, aside, children }: { testId: string; title: string; aside?: ReactNode; children: ReactNode }) {
  return (
    <div data-testid={testId} className="flex min-w-0 flex-col gap-2.5 px-4 py-3">
      <div className="flex items-baseline justify-between gap-2">
        <span className="text-[11px] tracking-wide text-muted-foreground uppercase">{title}</span>
        {aside ? <span className="text-xs text-muted-foreground">{aside}</span> : null}
      </div>
      {children}
    </div>
  );
}

function SampleBar({
  label,
  count,
  threshold,
  unit,
  tip,
  bar,
  barText,
}: {
  label: string;
  count: number;
  threshold: number;
  unit: string;
  tip: string;
  bar: string;
  barText: string;
}) {
  const text = count >= threshold ? `${formatCount(count)} ${unit}` : `${formatCount(count)}/${formatCount(threshold)} ${unit}`;
  const filled = share(count, threshold);
  return (
    <ReasonTip reason={tip}>
      <div
        role="progressbar"
        aria-label={label}
        aria-valuemin={0}
        aria-valuemax={threshold}
        aria-valuenow={Math.min(count, threshold)}
        aria-valuetext={text}
        className="num relative h-4 w-full cursor-help overflow-hidden rounded-full bg-muted text-[10px] leading-4"
      >
        <span className="absolute inset-0 truncate px-1.5 text-center text-muted-foreground">{text}</span>
        <div
          className={cn("absolute inset-0 rounded-full", bar)}
          style={{
            clipPath: `inset(0 ${percent(1 - filled)} 0 0 round 9999px)`,
          }}
          aria-hidden="true"
        >
          <span className={cn("absolute inset-0 truncate px-1.5 text-center", barText)}>{text}</span>
        </div>
      </div>
    </ReasonTip>
  );
}

const CANDIDATE_FILL = { bar: "bg-primary", barText: "text-primary-foreground" };
const BASELINE_FILL = { bar: "bg-muted-foreground/45", barText: "text-foreground" };
const EARLY = " A strong regression can be confirmed earlier.";

function needs(count: number, need: number, done: string, extra = ""): string {
  return count < need ? `Needs ${formatCount(need - count)} more.${extra}` : done;
}

function SampleBlock({ detail, settings }: { detail: ReleaseDetail; settings: VerdictSettings | undefined }) {
  const evaluation = detail.evaluation;
  const minTurns = settings?.min_turns ?? 200;
  const minSessions = settings?.min_sessions ?? 30;
  const candidate = evaluation?.n_candidate_turns ?? 0;
  const candidateSessions = evaluation?.n_candidate_sessions ?? 0;
  const baseline = evaluation?.n_baseline_turns ?? 0;
  const baselineSessions = evaluation?.n_baseline_sessions ?? 0;
  const baselineName = detail.baseline.release ?? "n/a";
  return (
    <Block
      testId="release-sample"
      title="Sample"
      aside={
        <span title="A strong regression can be confirmed before the full sample.">
          full sample at {formatCount(minTurns)} turns, {formatCount(minSessions)} sessions
        </span>
      }
    >
      <div className="grid grid-cols-[minmax(0,6rem)_minmax(0,1fr)_minmax(0,1fr)] items-center gap-x-2 gap-y-2.5 text-xs">
        <span className="truncate text-muted-foreground">This release</span>
        <SampleBar
          label="This release turns"
          count={candidate}
          threshold={minTurns}
          unit="turns"
          tip={`Turns from this release toward the full sample of ${formatCount(minTurns)}. ${needs(candidate, minTurns, "Full sample reached.", EARLY)}`}
          {...CANDIDATE_FILL}
        />
        <SampleBar
          label="This release sessions"
          count={candidateSessions}
          threshold={minSessions}
          unit="sessions"
          tip={`Sessions from this release. Turns in one session are alike, so a healthy verdict also needs ${formatCount(minSessions)} separate sessions. ${needs(candidateSessions, minSessions, "Reached.", EARLY)}`}
          {...CANDIDATE_FILL}
        />
        <span className="truncate text-muted-foreground">Baseline</span>
        <SampleBar
          label="Baseline turns"
          count={baseline}
          threshold={minTurns}
          unit="turns"
          tip={`Turns from the baseline release ${baselineName}. The verdict waits until it has ${formatCount(minTurns)}. ${needs(baseline, minTurns, "Ready.")}`}
          {...BASELINE_FILL}
        />
        <SampleBar
          label="Baseline sessions"
          count={baselineSessions}
          threshold={minSessions}
          unit="sessions"
          tip={`Sessions from the baseline release ${baselineName}. The verdict waits until it has ${formatCount(minSessions)}. ${needs(baselineSessions, minSessions, "Ready.")}`}
          {...BASELINE_FILL}
        />
      </div>
    </Block>
  );
}

function endLabel(detail: ReleaseDetail, monitored: number, now: number): string {
  if (detail.final) {
    const verb = detail.summary?.ended?.reason === "stopped" ? "Stopped" : "Ended";
    return `${verb} after ${formatDuration(monitored / 1000)}`;
  }
  if (detail.user_state.stopped_at) {
    return "Stopping, final check queued";
  }
  const until = formatUntil(detail.max_window_end, now);
  return until && until !== "overdue" ? `Ends ${until}` : "Ending";
}

const HINT =
  "cursor-help rounded-sm underline decoration-muted-foreground/50 decoration-dotted underline-offset-2 outline-none focus-visible:ring-2 focus-visible:ring-primary";

function Hint({ tip, testId, className, children }: { tip: TipContent; testId?: string; className?: string; children: ReactNode }) {
  return (
    <Tip content={<TipBody tip={tip} />}>
      <span tabIndex={0} data-testid={testId} aria-label={spoken(tip)} className={cn(HINT, className)}>
        {children}
      </span>
    </Tip>
  );
}

const at = (iso: string, now: number) => `${formatUtcShort(iso, now)} UTC`;

function took(ms: number): string {
  return ms < 1000 ? `${formatCount(ms)} ms` : `${(ms / 1000).toFixed(1)} s`;
}

function lastCheckTip(detail: ReleaseDetail, settings: VerdictSettings | undefined, last: string, now: number): TipContent {
  const evaluation = detail.evaluation;
  if (!evaluation) {
    return { title: "Last check", facts: [{ label: "At", value: at(last, now) }], notes: [] };
  }
  const mixedCounted = settings?.include_mixed_sessions ?? false;
  const mixed = evaluation.n_excluded_mixed;
  const causes: [number, string][] = [
    [mixedCounted ? 0 : mixed, "from mixed sessions, which also ran another release"],
    [evaluation.n_excluded_untagged, "without a release tag"],
    [evaluation.n_excluded_late, "late, sent long after they ran"],
  ];
  const leftOut = causes.reduce((sum, [count]) => sum + count, 0);
  const notes = causes.filter(([count]) => count > 0).map(([count, why]) => `${formatCount(count)} ${why}.`);
  if (mixedCounted && mixed > 0) {
    notes.push(`${formatCount(mixed)} turns from mixed sessions are counted, because this agent includes mixed sessions.`);
  }
  return {
    title: "Last check",
    facts: [
      { label: "Trigger", value: evaluation.manual ? "Manual" : "Scheduled" },
      { label: "At", value: at(last, now) },
      { label: "Took", value: took(evaluation.duration_ms) },
      { label: "Left out", value: leftOut > 0 ? `${formatCount(leftOut)} turns` : "None" },
    ],
    notes,
  };
}

function nextCheckTip(due: string, overdue: boolean, now: number): TipContent {
  return {
    title: overdue ? "Next check is late" : "Next check",
    facts: [{ label: overdue ? "Was due" : "At", value: at(due, now) }],
    notes: overdue ? ["This check should have run by now. The worker may be behind or stopped."] : [],
  };
}

const PAUSED_TIP: TipContent = {
  title: "Checks paused",
  facts: [],
  notes: ["Checks resume when a new turn arrives. Otherwise the last check runs when the window ends."],
};

function lastTurnTip(seen: string, live: boolean, now: number): TipContent {
  return {
    title: "Last turn",
    meaning: "The latest turn received from this release.",
    facts: [{ label: "At", value: at(seen, now) }],
    notes: live ? ["Checks pause after 24 h without new turns."] : [],
  };
}

function confirmationTip(reason: string, confirmations: { done: number; needed: number }): TipContent {
  const verdict = reason === "fail_candidate" ? "A regression" : "Healthy";
  const rule = reason === "fail_candidate" ? "find it" : "pass";
  return {
    title: "Confirmation",
    meaning: `${verdict} is confirmed after ${confirmations.needed} checks in a row ${rule}.`,
    facts: [{ label: "So far", value: `${Math.min(confirmations.done, confirmations.needed)} of ${confirmations.needed}` }],
    notes: ["Changing the baseline or the expected changes starts over."],
  };
}

function MonitoringBlock({
  detail,
  summary,
  history,
  events,
  settings,
  now,
}: {
  detail: ReleaseDetail;
  summary: VerdictSummary;
  history: EvaluationOut[];
  events: ReleaseEventOut[];
  settings: VerdictSettings | undefined;
  now: number;
}) {
  const timeline = buildTimeline(detail, history, events, now);
  const span = timeline.cap - timeline.start;
  const monitored = timeline.end - timeline.start;
  const last = detail.timing.last_check_at;
  const next = detail.final || timeline.idle ? null : formatUntil(detail.timing.next_check_at, now);
  const confirmations = summary.confirmations;
  return (
    <Block testId="release-timing" title="Monitoring window" aside={`up to ${formatDuration(span / 1000)}`}>
      <MonitoringTrack
        timeline={timeline}
        label={`Monitored ${formatDuration(monitored / 1000)} of ${formatDuration(span / 1000)}, ${history.length} checks`}
      />
      <div className="flex items-baseline justify-between gap-2 text-xs">
        <span>
          First seen <TimeAgo iso={detail.first_seen} />
        </span>
        <span className="text-right">{endLabel(detail, monitored, now)}</span>
      </div>
      <p data-testid="release-checks" className="m-0 flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted-foreground">
        {last ? (
          <Hint testId="release-last-check" tip={lastCheckTip(detail, settings, last, now)}>
            Last check <time dateTime={last}>{formatRelative(last, now)}</time>
          </Hint>
        ) : null}
        {next && detail.timing.next_check_at ? (
          <Hint testId="release-next-check" tip={nextCheckTip(detail.timing.next_check_at, next === "overdue", now)}>
            Next check {next}
          </Hint>
        ) : null}
        {timeline.idle ? <Hint tip={PAUSED_TIP}>Checks paused: no traffic for over 24 h</Hint> : null}
        {detail.last_seen ? (
          <Hint testId="release-last-turn" tip={lastTurnTip(detail.last_seen, !detail.final, now)}>
            Last turn <time dateTime={detail.last_seen}>{formatRelative(detail.last_seen, now)}</time>
          </Hint>
        ) : null}
        {confirmations ? (
          <Hint
            testId="release-confirmations"
            tip={confirmationTip(detail.reason, confirmations)}
            className="inline-flex items-center gap-1.5"
          >
            <span className="flex gap-0.5" aria-hidden="true">
              {Array.from({ length: confirmations.needed }, (_, index) => (
                <span
                  key={index}
                  className={cn(
                    "size-2 rounded-full border",
                    index < confirmations.done ? "border-transparent bg-foreground/70" : "border-muted-foreground/50",
                  )}
                />
              ))}
            </span>
            {Math.min(confirmations.done, confirmations.needed)} of {confirmations.needed} confirmations
          </Hint>
        ) : null}
      </p>
    </Block>
  );
}

export function ReleaseStrip({
  detail,
  summary,
  history,
  events = [],
  settings,
  now = Date.now(),
}: {
  detail: ReleaseDetail;
  summary: VerdictSummary;
  history: EvaluationOut[];
  events?: ReleaseEventOut[];
  settings: VerdictSettings | undefined;
  now?: number;
}) {
  return (
    <div className="grid divide-y divide-border rounded-lg border border-border bg-card md:grid-cols-2 md:divide-x md:divide-y-0">
      <SampleBlock detail={detail} settings={settings} />
      <MonitoringBlock detail={detail} summary={summary} history={history} events={events} settings={settings} now={now} />
    </div>
  );
}
