import { CircleAlert, CircleCheck, Info, TriangleAlert } from "lucide-react";
import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

const TONES = {
  info: { box: "border-l-primary bg-card", icon: "text-primary", Icon: Info },
  success: { box: "border-l-pass bg-pass-bg", icon: "text-pass", Icon: CircleCheck },
  warning: { box: "border-l-inconclusive bg-inconclusive-bg", icon: "text-inconclusive", Icon: TriangleAlert },
  fail: { box: "border-l-fail bg-fail-bg", icon: "text-fail", Icon: CircleAlert },
} as const;

export function Notice({
  tone = "info",
  title,
  children,
  testId,
}: {
  tone?: keyof typeof TONES;
  title?: string;
  children: ReactNode;
  testId?: string;
}) {
  const { box, icon, Icon } = TONES[tone];
  return (
    <div
      data-testid={testId}
      role={tone === "fail" ? "alert" : "status"}
      className={cn("flex gap-2.5 rounded-lg border border-l-4 border-border px-3.5 py-2.5 text-sm", box)}
    >
      <Icon size={16} strokeWidth={2} aria-hidden="true" className={cn("mt-0.5 shrink-0", icon)} />
      <div className="min-w-0">
        {title ? <p className="m-0 font-semibold">{title}</p> : null}
        <div className="text-foreground">{children}</div>
      </div>
    </div>
  );
}
