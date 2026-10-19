import type { MetricItem, SliceDimensionBlock, SliceValue } from "@/api/types";
import { InfoTip } from "@/components/ui/tooltip";
import { formatCount, formatDelta, formatValue } from "@/lib/format";
import { SLICE_DIMENSION_LABELS, SLICE_DIMENSIONS, sliceReasonLabel } from "@/lib/metrics";
import { cn } from "@/lib/utils";

const STATUS_WORDS: Record<string, string> = { FAIL: "regressed", NOT_FLAGGED: "not flagged" };
const COMPARED = new Set(["FAIL", "NOT_FLAGGED"]);

type Skipped = { dimension: string; row: SliceValue };

function plural(count: number, one: string, many = `${one}s`): string {
  return `${formatCount(count)} ${count === 1 ? one : many}`;
}

function NotCompared({
  skipped,
  notApplicable,
  noun,
  minTurns,
}: {
  skipped: Skipped[];
  notApplicable: string[];
  noun: string;
  minTurns: number;
}) {
  const groups = new Map<string, Skipped[]>();
  for (const item of skipped) {
    const key = item.row.reason ?? "";
    groups.set(key, [...(groups.get(key) ?? []), item]);
  }
  const parts = [
    skipped.length > 0 ? `${plural(skipped.length, "value")} not compared` : null,
    notApplicable.length > 0 ? `${plural(notApplicable.length, "dimension")} not applicable` : null,
  ].filter(Boolean);
  return (
    <details data-testid="slices-not-compared" className="text-sm">
      <summary className="cursor-pointer text-xs text-muted-foreground hover:text-foreground">{parts.join(" · ")}</summary>
      <div className="mt-3 flex flex-col gap-4">
        {[...groups].map(([reason, rows]) => (
          <div key={reason} data-testid={`slices-reason-${reason || "unknown"}`} className="flex flex-col gap-1">
            <p className="m-0 text-xs font-medium text-foreground">
              {reason === "few_turns" ? `Too few ${noun} (needs ${formatCount(minTurns)} on each side)` : sliceReasonLabel(reason)}
            </p>
            <table className="w-[85%] min-w-[40rem] table-fixed border-collapse text-xs">
              <colgroup>
                <col />
                <col className="w-40" />
                <col className="w-40" />
              </colgroup>
              <thead className="sr-only">
                <tr>
                  <th>Value</th>
                  <th>Dimension</th>
                  <th>Previous / this release</th>
                </tr>
              </thead>
              <tbody>
                {rows.map(({ dimension, row }) => {
                  const short = reason === "few_turns";
                  return (
                    <tr key={`${dimension}-${row.value}`} data-testid={`slice-skipped-${dimension}-${row.value}`} className="text-muted-foreground">
                      <td className="mono truncate py-1 pr-3">{row.value === "" ? "(none)" : row.value}</td>
                      <td className="py-1 pr-3">{SLICE_DIMENSION_LABELS[dimension] ?? dimension}</td>
                      <td className="num py-1 text-right whitespace-nowrap">
                        <span className={cn(short && row.n_baseline < minTurns && "font-medium text-foreground")}>{formatCount(row.n_baseline)}</span>
                        {" / "}
                        <span className={cn(short && row.n_candidate < minTurns && "font-medium text-foreground")}>{formatCount(row.n_candidate)}</span>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        ))}
        {notApplicable.length > 0 ? (
          <p className="m-0 text-xs text-muted-foreground">
            Not applicable for this metric:{" "}
            {notApplicable.map((dimension, index) => (
              <span key={dimension} data-testid={`slice-dimension-${dimension}`}>
                {index > 0 ? ", " : ""}
                {SLICE_DIMENSION_LABELS[dimension] ?? dimension}
                <span className="sr-only"> not applicable</span>
              </span>
            ))}
          </p>
        ) : null}
      </div>
    </details>
  );
}

export function SlicesSection({
  items,
  slices,
  metric,
  minTurns = 100,
}: {
  items: Record<string, MetricItem> | undefined;
  slices: Record<string, Record<string, SliceDimensionBlock>> | undefined;
  metric: string;
  minTurns?: number;
}) {
  const family = slices?.[metric] ?? {};
  const current = items?.[metric];
  const mode = current?.tolerance_mode ?? "abs";
  const unit = current?.unit ?? "rate";
  const blocks = SLICE_DIMENSIONS.map((dimension) => {
    const block = family[dimension] ?? { applicable: false, values: [] };
    const rows = block.values.filter((row) => COMPARED.has(row.status));
    return { dimension, block, rows, failing: rows.filter((row) => row.status === "FAIL").length };
  });
  const compared = blocks.filter(({ block, rows }) => block.applicable && rows.length > 0);
  const skipped: Skipped[] = blocks.flatMap(({ dimension, block }) =>
    block.applicable ? block.values.filter((row) => !COMPARED.has(row.status)).map((row) => ({ dimension, row })) : [],
  );
  const notApplicable = blocks.filter(({ block }) => !block.applicable).map(({ dimension }) => dimension);
  const footer =
    skipped.length > 0 || notApplicable.length > 0 ? (
      <NotCompared skipped={skipped} notApplicable={notApplicable} noun={current?.level === "tool" ? "tool calls" : "turns"} minTurns={minTurns} />
    ) : null;

  if (compared.length === 0) {
    return (
      <section data-testid="slices-section" className="flex flex-col gap-2">
        <p className="m-0 text-sm text-muted-foreground">
          {skipped.length > 0 ? "No slice has enough data to compare yet." : "No slices for this metric."}
        </p>
        {footer}
      </section>
    );
  }
  return (
    <section data-testid="slices-section" className="flex flex-col gap-5">
      {compared.map(({ dimension, rows, failing: failingCount }) => {
        return (
          <div key={dimension} data-testid={`slice-dimension-${dimension}`} className="flex flex-col gap-1.5">
            <h4 className="m-0 flex items-center gap-1.5 text-xs font-semibold text-foreground">
              {SLICE_DIMENSION_LABELS[dimension] ?? dimension}
              {failingCount > 0 ? (
                <span className="num rounded-full bg-fail-bg px-1.5 font-semibold text-fail">
                  {failingCount}
                  <span className="sr-only"> regressed</span>
                </span>
              ) : null}
              {dimension === "tool" ? (
                <InfoTip label="tool slices">A turn can call several tools, so these slices overlap.</InfoTip>
              ) : null}
            </h4>
            <div className="overflow-x-auto">
              <table className="w-[85%] min-w-[40rem] table-fixed border-collapse text-sm">
                <colgroup>
                  <col />
                  <col className="w-28" />
                  <col className="w-28" />
                  <col className="w-28" />
                  <col className="w-28" />
                </colgroup>
                <thead className="text-left text-xs text-muted-foreground">
                  <tr>
                    <th className="px-3 py-1.5 font-medium">Value</th>
                    <th className="px-3 py-1.5 text-right font-medium">Previous</th>
                    <th className="px-3 py-1.5 text-right font-medium">This release</th>
                    <th className="px-3 py-1.5 text-right font-medium">Change</th>
                    <th className="px-3 py-1.5 text-right font-medium">
                      <span className="inline-flex items-center gap-1 align-middle">
                        Turns
                        <InfoTip label="turns">
                          Turns measured in the previous release / this release. Fewer turns make the change less certain.
                        </InfoTip>
                      </span>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row) => {
                    const label = row.value === "" ? "(none)" : row.value;
                    const failing = row.status === "FAIL";
                    return (
                      <tr
                        key={`${dimension}-${row.value}`}
                        data-testid={`slice-row-${dimension}-${row.value}`}
                        data-status={row.status}
                        className="border-t border-border"
                      >
                        <td className={cn("mono truncate px-3 py-2", failing ? "font-medium text-foreground" : "text-muted-foreground")}>
                          {label}
                          <span className="sr-only">, {STATUS_WORDS[row.status] ?? row.status}</span>
                        </td>
                        <td className="num px-3 py-2 text-right text-muted-foreground">{formatValue(row.baseline, unit)}</td>
                        <td className="num px-3 py-2 text-right">{formatValue(row.candidate, unit)}</td>
                        <td
                          className="num px-3 py-2 text-right whitespace-nowrap"
                          title={row.p_adjusted == null ? undefined : `Adjusted p-value ${row.p_adjusted.toFixed(4)}`}
                        >
                          <span className={cn(failing && "font-semibold text-fail")}>{formatDelta(row.delta, mode)}</span>
                        </td>
                        <td className="num px-3 py-2 text-right text-xs whitespace-nowrap text-muted-foreground">
                          {formatCount(row.n_baseline)} / {formatCount(row.n_candidate)}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        );
      })}
      {footer}
    </section>
  );
}
