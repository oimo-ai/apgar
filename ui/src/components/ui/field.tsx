import type { ReactNode } from "react";

import { InfoTip } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

export function RequiredMark() {
  return (
    <span aria-hidden="true" className="ml-0.5 text-fail">
      *
    </span>
  );
}

export function FieldError({ children }: { children: ReactNode }) {
  return <span className="text-fail">{children}</span>;
}

export function Field({
  label,
  htmlFor,
  hint,
  info,
  required = false,
  className,
  children,
}: {
  label: string;
  htmlFor?: string;
  hint?: ReactNode;
  info?: string;
  required?: boolean;
  className?: string;
  children: ReactNode;
}) {
  return (
    <div className={cn("flex min-w-0 flex-col gap-1.5", className)}>
      <span className="inline-flex items-center gap-1 text-xs font-medium">
        <label htmlFor={htmlFor}>
          {label}
          {required ? <RequiredMark /> : null}
        </label>
        {info ? <InfoTip label={label}>{info}</InfoTip> : null}
      </span>
      {children}
      {hint ? <p className="m-0 text-xs text-muted-foreground">{hint}</p> : null}
    </div>
  );
}
