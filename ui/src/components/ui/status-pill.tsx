import { cn } from "@/lib/utils";

const TONE: Record<string, string> = {
  ok: "bg-pass-bg text-pass",
  active: "bg-pass-bg text-pass",
  sent: "bg-pass-bg text-pass",
  error: "bg-fail-bg text-fail",
  failed: "bg-fail-bg text-fail",
  pending: "bg-inconclusive-bg text-inconclusive",
};

export function StatusPill({ status, testId }: { status: string; testId?: string }) {
  return (
    <span data-testid={testId} className={cn("pill pill-dot", TONE[status])}>
      {status}
    </span>
  );
}
