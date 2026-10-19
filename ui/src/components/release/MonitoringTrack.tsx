import { CircleStop, Flag, GitCompareArrows, ListChecks, type LucideIcon } from "lucide-react";
import { Fragment, useLayoutEffect, useRef, useState, type CSSProperties } from "react";

import { Tip } from "@/components/ui/tooltip";
import { timeScale, type Marker, type MarkerKind, type SegmentKind, type Timeline, type TipContent } from "@/lib/monitoringTimeline";
import { cn } from "@/lib/utils";

const SEGMENT_FILL: Record<SegmentKind, string> = {
  regression: "bg-fail",
  possible_regression: "bg-inconclusive",
  healthy: "bg-pass",
  looks_healthy: "bg-pass/45",
  not_enough_data: "bg-muted-foreground/55",
  unconfirmed: "bg-muted-foreground/70",
  collecting: "bg-muted-foreground/30",
  first_release: "bg-muted-foreground/30",
};

const MARKER_ICON: Record<Exclude<MarkerKind, "now">, LucideIcon> = {
  baseline: GitCompareArrows,
  expected: ListChecks,
  stop: CircleStop,
  end: Flag,
};

const STRIPES: CSSProperties = {
  backgroundImage: "repeating-linear-gradient(135deg, var(--border-strong) 0 1px, transparent 1px 6px)",
};

const MIN_SEGMENT_PX = 10;
const MERGE_WITHIN_PX = 18;
const MAX_TIPS = 4;

function percent(value: number, total: number): string {
  return `${((total > 0 ? Math.min(1, Math.max(0, value / total)) : 0) * 100).toFixed(3)}%`;
}

function useInnerWidth<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  const [width, setWidth] = useState(0);
  useLayoutEffect(() => {
    const node = ref.current;
    if (!node || typeof ResizeObserver === "undefined") {
      return;
    }
    const observer = new ResizeObserver(([entry]) => setWidth(entry.contentRect.width));
    observer.observe(node);
    return () => observer.disconnect();
  }, []);
  return [ref, width] as const;
}

function groupMarkers(markers: Marker[], at: (ts: number) => number, within: number): Marker[][] {
  const groups: Marker[][] = [];
  const order = (marker: Marker) => (marker.kind === "end" ? 0 : 1);
  for (const marker of [...markers].sort((left, right) => left.at - right.at || order(left) - order(right))) {
    const last = groups[groups.length - 1];
    if (last && marker.kind !== "now" && last[0].kind !== "now" && at(marker.at) - at(last[last.length - 1].at) < within) {
      last.push(marker);
    } else {
      groups.push([marker]);
    }
  }
  return groups;
}

export function spoken(tip: TipContent): string {
  const parts = [tip.title, tip.meaning, ...tip.facts.map((fact) => `${fact.label} ${fact.value}`), ...tip.notes];
  return parts.flatMap((part) => (part ? [part.replace(/\.$/, "")] : [])).join(". ") + ".";
}

export function TipBody({ tip, swatch }: { tip: TipContent; swatch?: string }) {
  return (
    <div className="flex min-w-44 flex-col gap-1.5">
      <p className="m-0 flex items-center gap-1.5 font-semibold">
        {swatch ? <span className={cn("size-2.5 shrink-0 rounded-sm", swatch)} aria-hidden="true" /> : null}
        {tip.title}
      </p>
      {tip.meaning ? <p className="m-0 opacity-80">{tip.meaning}</p> : null}
      {tip.facts.length > 0 ? (
        <dl className="m-0 grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-0.5">
          {tip.facts.map((fact) => (
            <Fragment key={fact.label}>
              <dt className="opacity-60">{fact.label}</dt>
              <dd className={cn("m-0 break-words", fact.mono && "font-mono")}>{fact.value}</dd>
            </Fragment>
          ))}
        </dl>
      ) : null}
      {tip.notes.length > 0 ? (
        <div className="flex flex-col gap-0.5 border-t border-background/20 pt-1.5">
          {tip.notes.map((note) => (
            <p key={note} className="m-0 opacity-80">
              {note}
            </p>
          ))}
        </div>
      ) : null}
    </div>
  );
}

const FOCUS = "focus-visible:ring-2 focus-visible:ring-primary focus-visible:outline-none focus-visible:ring-inset";

export function MonitoringTrack({ timeline, label }: { timeline: Timeline; label: string }) {
  const [trackRef, width] = useInnerWidth<HTMLDivElement>();
  const total = width > 0 ? width : 1;
  const spans = [...timeline.segments, ...(timeline.rest ? [{ from: timeline.end, to: timeline.cap }] : [])];
  const { boxes, at } = timeScale(spans, total, width > 0 ? MIN_SEGMENT_PX : 0);
  const restBox = timeline.rest ? boxes[boxes.length - 1] : null;
  const place = (x: number, size: number): CSSProperties => ({ left: percent(x, total), width: percent(size, total) });
  return (
    <div className="relative pt-5">
      <div
        ref={trackRef}
        data-testid="monitoring-track"
        role="group"
        aria-label={label}
        className="relative h-5 overflow-hidden rounded-md border border-input bg-card"
      >
        {timeline.segments.map((segment, index) => (
          <Tip key={`${segment.kind}-${segment.from}-${index}`} content={<TipBody tip={segment.tip} swatch={SEGMENT_FILL[segment.kind]} />}>
            <div
              tabIndex={0}
              data-testid="monitoring-segment"
              data-kind={segment.kind}
              data-stale={segment.stale ? "true" : undefined}
              aria-label={spoken(segment.tip)}
              className={cn("absolute inset-y-0 border-l border-card first:border-l-0", FOCUS)}
              style={place(boxes[index].x, boxes[index].width)}
            >
              <span
                className={cn(
                  "absolute inset-x-0",
                  segment.stale ? "top-1/2 h-1 -translate-y-1/2" : "inset-y-0",
                  SEGMENT_FILL[segment.kind],
                )}
              />
            </div>
          </Tip>
        ))}
        {timeline.rest && restBox ? (
          <Tip content={<TipBody tip={timeline.rest} />}>
            <div
              tabIndex={0}
              data-testid="monitoring-rest"
              aria-label={spoken(timeline.rest)}
              className={cn("absolute inset-y-0", FOCUS)}
              style={{ ...place(restBox.x, restBox.width), ...STRIPES }}
            />
          </Tip>
        ) : null}
      </div>
      <div className="pointer-events-none absolute inset-x-px top-0 -bottom-1">
        {groupMarkers(timeline.markers, at, width > 0 ? MERGE_WITHIN_PX : 0.015).map((group) => {
          const marker = group.find((item) => item.kind === "end") ?? group[group.length - 1];
          const hidden = group.length - MAX_TIPS;
          const body = (
            <div className="flex flex-col gap-2.5">
              {group.slice(0, MAX_TIPS).map((item, index) => (
                <div key={`${item.kind}-${item.at}-${index}`} className={cn(index > 0 && "border-t border-background/20 pt-2.5")}>
                  <TipBody tip={item.tip} />
                </div>
              ))}
              {hidden > 0 ? (
                <p className="m-0 border-t border-background/20 pt-2.5 opacity-60">{hidden} more at about the same time</p>
              ) : null}
            </div>
          );
          if (marker.kind === "now") {
            return (
              <Tip key="now" content={body}>
                <span
                  tabIndex={0}
                  data-testid="monitoring-now"
                  aria-label={spoken(marker.tip)}
                  className="pointer-events-auto absolute top-3 bottom-0 flex w-3 -translate-x-1/2 justify-center outline-none focus-visible:ring-2 focus-visible:ring-primary"
                  style={{ left: percent(at(marker.at), total) }}
                >
                  <span className="w-0.5 rounded-full bg-foreground" />
                </span>
              </Tip>
            );
          }
          const Icon = MARKER_ICON[marker.kind];
          return (
            <span
              key={`${marker.kind}-${marker.at}-${group.length}`}
              className="absolute top-0 bottom-0 flex -translate-x-1/2 flex-col items-center"
              style={{ left: percent(at(marker.at), total) }}
            >
              <Tip content={body}>
                <button
                  type="button"
                  data-testid={`monitoring-marker-${marker.kind}`}
                  aria-label={group.map((item) => spoken(item.tip)).join(" ")}
                  className="pointer-events-auto relative grid size-4 cursor-help place-items-center rounded-full border border-input bg-card text-foreground"
                >
                  <Icon size={10} strokeWidth={2.5} aria-hidden="true" />
                  {group.length > 1 ? (
                    <span className="num absolute -top-1.5 left-3.5 rounded-full bg-foreground px-1 text-[10px] leading-3.5 text-background">
                      {group.length}
                    </span>
                  ) : null}
                </button>
              </Tip>
              <span className="w-px flex-1 bg-foreground/60" />
            </span>
          );
        })}
      </div>
    </div>
  );
}
