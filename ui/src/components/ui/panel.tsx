import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

export function Panel({ className, children, testId }: { className?: string; children: ReactNode; testId?: string }) {
  return (
    <section data-testid={testId} className={cn("rounded-lg border border-border bg-card", className)}>
      {children}
    </section>
  );
}

export function PanelHeader({
  title,
  description,
  actions,
}: {
  title: string;
  description?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-3 border-b border-border px-4 py-3">
      <div className="min-w-0">
        <h3 className="m-0 text-sm font-semibold">{title}</h3>
        {description ? <p className="m-0 mt-0.5 text-xs text-muted-foreground">{description}</p> : null}
      </div>
      {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
    </div>
  );
}

export function PanelBody({ className, children }: { className?: string; children: ReactNode }) {
  return <div className={cn("p-4", className)}>{children}</div>;
}

export function PanelFooter({ children }: { children: ReactNode }) {
  return <div className="flex flex-wrap items-center justify-end gap-2 border-t border-border px-4 py-3">{children}</div>;
}

export function TableEmpty({ colSpan, children }: { colSpan: number; children: ReactNode }) {
  return (
    <tr>
      <td colSpan={colSpan} className="py-8 text-center text-muted-foreground">
        {children}
      </td>
    </tr>
  );
}
