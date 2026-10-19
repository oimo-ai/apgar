import { Link } from "@tanstack/react-router";
import {
  ArrowRightLeft,
  CircleCheck,
  CircleDashed,
  CircleDot,
  CircleHelp,
  CircleStop,
  CircleX,
  Clock,
  Flag,
  Hourglass,
  Loader2,
  type LucideIcon,
  TriangleAlert,
} from "lucide-react";

import type { ReleaseDetail } from "@/api/types";
import { ReasonTip } from "@/components/ui/tooltip";
import { releaseStatus, type ReleaseStatus as Status, type StatusKind } from "@/lib/releaseStatus";
import { cn } from "@/lib/utils";

const MUTED = "bg-muted text-muted-foreground";

const KIND: Record<StatusKind, { Icon: LucideIcon; style: string }> = {
  regression: { Icon: CircleX, style: "bg-fail-bg text-fail" },
  healthy: { Icon: CircleCheck, style: "bg-pass-bg text-pass" },
  possible_regression: { Icon: TriangleAlert, style: "bg-inconclusive-bg text-inconclusive" },
  looks_healthy: { Icon: CircleCheck, style: "border border-dashed border-pass/60 text-pass" },
  not_enough_data: { Icon: CircleDashed, style: MUTED },
  unconfirmed: { Icon: CircleHelp, style: MUTED },
  collecting: { Icon: Hourglass, style: MUTED },
  waiting: { Icon: Clock, style: MUTED },
  first_release: { Icon: CircleDot, style: MUTED },
};

const PHASE_ICON: Record<Exclude<Status["phase"]["kind"], "monitoring">, LucideIcon> = {
  stopping: Loader2,
  ended: Flag,
  stopped: CircleStop,
  replaced: ArrowRightLeft,
};

function Phase({ phase, agent, final }: { phase: Status["phase"]; agent: string; final: boolean }) {
  const Icon = phase.kind === "monitoring" ? null : PHASE_ICON[phase.kind];
  const body = (
    <span
      data-testid={final ? "release-final" : "release-phase"}
      className="inline-flex items-center gap-1.5 text-xs text-muted-foreground"
    >
      {Icon ? (
        <Icon size={13} aria-hidden="true" className={cn(phase.kind === "stopping" && "animate-spin")} />
      ) : (
        <span className="relative flex size-2" aria-hidden="true">
          <span className="absolute inline-flex size-full animate-ping rounded-full bg-muted-foreground/40" />
          <span className="relative inline-flex size-2 rounded-full bg-muted-foreground/70" />
        </span>
      )}
      {phase.label}
      {phase.by ? (
        <Link to="/agents/$agent/releases/$release" params={{ agent, release: phase.by }} className="mono">
          {phase.by}
        </Link>
      ) : null}
    </span>
  );
  if (!phase.by) {
    return body;
  }
  return <ReasonTip reason={`${phase.by} started receiving traffic, so monitoring of this release ended.`}>{body}</ReasonTip>;
}

export function ReleaseStatus({ detail }: { detail: ReleaseDetail }) {
  const status = releaseStatus(detail);
  const { Icon, style } = KIND[status.kind];
  const detectability = status.kind === "not_enough_data" ? detail.summary?.detectability : null;
  return (
    <div data-testid="release-status" data-state={detail.state} data-kind={status.kind} className="mt-3 flex items-center gap-2.5">
      <span className={cn("grid size-7 shrink-0 place-items-center rounded-full", style)} aria-hidden="true">
        <Icon size={16} strokeWidth={2.25} />
      </span>
      <div className="flex min-w-0 flex-col gap-0.5">
        <div className="flex flex-wrap items-center gap-x-2.5 gap-y-1">
          <span data-testid="release-status-title" className="text-sm font-semibold">
            {status.title}
          </span>
          <span className="text-muted-foreground/60" aria-hidden="true">
            ·
          </span>
          <Phase phase={status.phase} agent={detail.agent} final={detail.final} />
        </div>
        {status.note ? (
          <p data-testid="release-status-note" className="m-0 text-sm text-muted-foreground">
            {detectability ? (
              <ReasonTip reason={detectability}>
                <span className="cursor-help underline decoration-dotted underline-offset-2">{status.note}</span>
              </ReasonTip>
            ) : (
              status.note
            )}
          </p>
        ) : null}
      </div>
    </div>
  );
}
