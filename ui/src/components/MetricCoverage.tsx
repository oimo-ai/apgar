import type { MetricCoverage as Coverage } from "@/api/types";
import { formatRate } from "@/lib/format";
import { METRIC_GROUPS, metricLabel } from "@/lib/metrics";

export function coverageText(coverage: Coverage): string {
  return `${coverage.active} of ${coverage.total} metrics active`;
}

export function MetricCoverage({ coverage }: { coverage: Coverage | null }) {
  if (!coverage) {
    return (
      <p data-testid="metric-coverage" className="m-0 text-sm text-muted-foreground">
        Metric coverage appears after the first check of a release.
      </p>
    );
  }
  const missing = coverage.metrics.filter((row) => !row.active);
  return (
    <details data-testid="metric-coverage" className="text-sm">
      <summary className="cursor-pointer">
        {coverageText(coverage)}
        {missing.length > 0 ? <span className="text-muted-foreground">, {missing.length} need more instrumentation</span> : null}
      </summary>
      <div className="mt-2 flex flex-col gap-2">
        {METRIC_GROUPS.map((group) => {
          const counts = coverage.groups[group.id];
          if (!counts || counts.total === 0) {
            return null;
          }
          const rows = missing.filter((row) => row.group === group.id);
          return (
            <div key={group.id} data-testid={`metric-coverage-${group.id}`}>
              <p className="m-0 text-xs font-medium text-muted-foreground">
                {group.title}: {counts.active} of {counts.total} active
              </p>
              {rows.length > 0 ? (
                <ul className="m-0 mt-1 flex list-none flex-col gap-0.5 p-0 text-xs">
                  {rows.map((row) => (
                    <li key={row.id}>
                      {metricLabel(row.id)}: missing {row.missing ?? "input"}
                      {row.share != null ? <span className="text-muted-foreground"> ({formatRate(row.share)} of units carry it)</span> : null}
                    </li>
                  ))}
                </ul>
              ) : null}
            </div>
          );
        })}
      </div>
    </details>
  );
}

const STEPS: Record<string, string[]> = {
  otlp: [
    "Tool arguments: set gen_ai.tool.call.arguments on tool spans. Retry rate and loop rate need it.",
    "Message content: set gen_ai.input.messages and gen_ai.output.messages, or turn on content capture in your instrumentation. Format failure rate and output length need it.",
    "Sessions: propagate session.id or gen_ai.conversation.id on every span. Turns per session needs it.",
  ],
  langfuse: [
    "Keep Fetch content on for the Langfuse connection, so tool arguments and message content are read.",
    "Turn on input and output capture in the Langfuse SDK. Retry rate, loop rate, format failure rate, and output length need it.",
    "Set a session id on traces. Turns per session needs it.",
  ],
};

export function InstrumentationSteps({ source, coverage }: { source: string; coverage: Coverage | null }) {
  return (
    <div data-testid="metric-setup" className="flex flex-col gap-2 text-sm">
      {coverage ? <MetricCoverage coverage={coverage} /> : <p className="m-0 font-medium">Metrics need these inputs</p>}
      <ul className="m-0 flex list-disc flex-col gap-1 pl-5 text-xs text-muted-foreground">
        {(STEPS[source] ?? []).map((step) => (
          <li key={step}>{step}</li>
        ))}
      </ul>
    </div>
  );
}
