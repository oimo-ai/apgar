import { Fragment, type ReactNode } from "react";

import type { MetricItem, MetricCoverage } from "@/api/types";
import { EmptyState } from "@/components/States";
import { TableGroup } from "@/components/ui/table-group";
import { ReasonTip } from "@/components/ui/tooltip";
import { formatDelta, formatValue } from "@/lib/format";
import { METRIC_GROUPS, type MetricId, metricDescription, metricLabel, naReasonLabel } from "@/lib/metrics";
import { cn } from "@/lib/utils";

const UNIT_WORDS: Record<string, string> = { tokens: "tokens", chars: "chars" };
const HEADERS = ["Metric", "Previous", "This release", "Change", "Status"];

export type MetricRowStatus =
  | "regressed"
  | "possible"
  | "within tolerance"
  | "not enough data"
  | "expected"
  | "informational"
  | "unavailable";

export function metricRowStatus(item: MetricItem, confirmed: boolean): MetricRowStatus {
  if (item.applicable === false || item.status === "NA") {
    return "unavailable";
  }
  if (item.status === "EXPECTED") {
    return "expected";
  }
  if (item.role === "informational") {
    return "informational";
  }
  if (item.status === "FAIL") {
    return confirmed ? "regressed" : "possible";
  }
  return item.status === "PASS" ? "within tolerance" : "not enough data";
}

function valueText(value: number | null | undefined, unit: string): string {
  const text = formatValue(value, unit);
  return value != null && UNIT_WORDS[unit] ? `${text} ${UNIT_WORDS[unit]}` : text;
}

function joinLabels(ids: string[]): string {
  const labels = ids.map((id, index) => (index === 0 ? metricLabel(id) : metricLabel(id).toLowerCase()));
  return labels.length < 2 ? labels.join("") : `${labels.slice(0, -1).join(", ")} and ${labels[labels.length - 1]}`;
}

export function unavailableLines(
  ids: string[],
  items: Record<string, MetricItem>,
  coverage: MetricCoverage | null | undefined,
): string[] {
  const byInput = new Map<string, string[]>();
  for (const id of ids) {
    const input = coverage?.metrics.find((row) => row.id === id)?.missing ?? naReasonLabel(items[id].na_reason).toLowerCase();
    byInput.set(input, [...(byInput.get(input) ?? []), id]);
  }
  return [...byInput].map(([input, group]) => `${joinLabels(group)} ${group.length > 1 ? "are" : "is"} unavailable: missing ${input}.`);
}

export function MetricsTable({
  items,
  coverage,
  selected,
  onSelect,
  confirmed = false,
  collecting = false,
  renderDetail,
  testId = "metrics-table",
}: {
  items: Record<string, MetricItem> | undefined;
  coverage?: MetricCoverage | null;
  selected?: string | null;
  onSelect?: (id: string) => void;
  confirmed?: boolean;
  collecting?: boolean;
  renderDetail?: (id: string) => ReactNode;
  testId?: string;
}) {
  if (!items || Object.keys(items).length === 0) {
    return <EmptyState>No check yet</EmptyState>;
  }
  const groups = METRIC_GROUPS.map((group) => {
    const ids = group.ids.filter((id) => items[id]);
    const unavailable = ids.filter((id) => metricRowStatus(items[id], confirmed) === "unavailable");
    return { ...group, rows: ids.filter((id) => !unavailable.includes(id)), unavailable };
  }).filter((group) => group.rows.length + group.unavailable.length > 0);
  return (
    <div className="overflow-x-auto" data-testid={testId}>
      <table className="w-full border-collapse text-sm">
        <thead className="border-b border-border text-left text-xs text-muted-foreground">
          <tr>
            {HEADERS.map((header, index) => (
              <th key={header} className={cn("px-4 py-2 font-medium whitespace-nowrap", index > 0 && index < 4 && "text-right")}>
                {header}
              </th>
            ))}
          </tr>
        </thead>
        {groups.map((group) => (
          <TableGroup key={group.id} title={group.title} colSpan={HEADERS.length}>
            {group.rows.map((id) => (
              <MetricRow
                key={id}
                id={id}
                item={items[id]}
                status={collecting ? null : metricRowStatus(items[id], confirmed)}
                active={selected === id}
                onSelect={onSelect}
                detail={selected === id ? renderDetail?.(id) : null}
              />
            ))}
            {group.unavailable.length > 0 ? (
              <tr data-testid={`metrics-unavailable-${group.id}`} className="border-t border-border">
                <td colSpan={HEADERS.length} className="px-4 py-2 text-xs text-muted-foreground">
                  {unavailableLines(group.unavailable, items, coverage).join(" ")}
                </td>
              </tr>
            ) : null}
          </TableGroup>
        ))}
      </table>
    </div>
  );
}

const STATUS_TONE: Partial<Record<MetricRowStatus, string>> = {
  regressed: "bg-fail-bg text-fail",
  possible: "bg-inconclusive-bg text-inconclusive",
  "within tolerance": "bg-pass-bg text-pass",
  informational: "bg-info-bg text-info",
};

function MetricRow({
  id,
  item,
  status,
  active,
  onSelect,
  detail,
}: {
  id: MetricId;
  item: MetricItem;
  status: MetricRowStatus | null;
  active: boolean;
  onSelect?: (id: string) => void;
  detail: ReactNode;
}) {
  const alarming = status === "regressed" || status === "possible";
  return (
    <Fragment>
      <tr
        data-testid={`metric-row-${id}`}
        aria-selected={onSelect ? active : undefined}
        aria-expanded={onSelect ? active : undefined}
        tabIndex={onSelect ? 0 : undefined}
        className={cn(
          "border-t border-border border-l-2 border-l-transparent",
          onSelect && "cursor-pointer hover:bg-muted",
          status === "regressed" && "border-l-fail bg-fail-bg",
          active && "bg-muted outline outline-1 -outline-offset-1 outline-primary",
        )}
        onClick={() => onSelect?.(id)}
        onKeyDown={(event) => {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            onSelect?.(id);
          }
        }}
      >
        <td className="px-4 py-2">
          <ReasonTip reason={metricDescription(id)}>
            <span className="font-medium whitespace-nowrap">{metricLabel(id)}</span>
          </ReasonTip>
        </td>
        <td className="num px-4 py-2 text-right whitespace-nowrap">{valueText(item.baseline, item.unit)}</td>
        <td className="num px-4 py-2 text-right whitespace-nowrap">{valueText(item.candidate, item.unit)}</td>
        <td className="num px-4 py-2 text-right whitespace-nowrap">
          <div className={cn(alarming && "font-semibold", status === "regressed" && "text-fail")}>
            {formatDelta(item.delta, item.tolerance_mode)}
          </div>
        </td>
        <td className="px-4 py-2" data-testid={`metric-status-${id}`}>
          {status === null ? (
            <span className="text-xs text-muted-foreground">so far</span>
          ) : (
            <span className={cn("pill", STATUS_TONE[status])}>{status}</span>
          )}
        </td>
      </tr>
      {detail ? (
        <tr data-testid={`metric-detail-${id}`} className="border-t border-border">
          <td colSpan={HEADERS.length} className="bg-card px-4 pt-3 pb-5">
            {detail}
          </td>
        </tr>
      ) : null}
    </Fragment>
  );
}
