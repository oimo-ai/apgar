import type { AgentSync } from "@/api/types";
import { Mono } from "@/components/Mono";
import { Notice } from "@/components/ui/notice";
import { StatusPill } from "@/components/ui/status-pill";
import { InfoTip } from "@/components/ui/tooltip";
import { formatUtc } from "@/lib/format";

function formatLag(seconds: number): string {
  if (seconds < 120) {
    return `${seconds}s`;
  }
  return `${Math.round(seconds / 60)} min`;
}

export function AgentSyncStatus({ source, sync }: { source: string; sync: AgentSync | null }) {
  if (source !== "langfuse" || sync == null) {
    return null;
  }
  return (
    <section data-testid="agent-sync-status" className="flex flex-col gap-3 rounded-lg border border-border bg-card px-4 py-3 text-sm">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
        <span className="inline-flex items-center gap-2 font-medium">
          Langfuse sync
          <StatusPill status={sync.status} />
        </span>
        <span className="text-muted-foreground">
          Synced up to {sync.watermark ? <Mono>{formatUtc(sync.watermark)}</Mono> : "n/a"}
        </span>
        {sync.lag_seconds == null ? null : (
          <span className="inline-flex items-center gap-1 text-muted-foreground">
            Behind by {formatLag(sync.lag_seconds)}
            <InfoTip label="Sync lag">
              Apgar reads Langfuse a little behind real time so late spans are not missed.
            </InfoTip>
          </span>
        )}
      </div>
      {sync.last_error ? (
        <Notice tone="fail" testId="sync-error">
          {sync.last_error}
        </Notice>
      ) : null}
    </section>
  );
}
