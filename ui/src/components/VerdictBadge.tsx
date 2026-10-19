import { releaseLabel, TONE_PILL } from "@/lib/releaseLabel";
import { cn } from "@/lib/utils";

export function VerdictBadge({
  state,
  reason,
  final,
  early,
  suffix,
}: {
  state: string;
  reason?: string | null;
  final?: boolean;
  early?: boolean;
  suffix?: string;
}) {
  const { label, tone } = releaseLabel({ state, reason, final, early });
  return (
    <span data-testid="verdict-badge" data-state={state} data-tone={tone} className={cn("pill", TONE_PILL[tone])}>
      {suffix ? `${label}: ${suffix}` : label}
    </span>
  );
}
