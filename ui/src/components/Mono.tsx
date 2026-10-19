import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

export function Mono({
  children,
  title,
  truncate = false,
}: {
  children: ReactNode;
  title?: string;
  truncate?: boolean;
}) {
  const label = title ?? (typeof children === "string" ? children : undefined);
  return (
    <span className={cn("mono", truncate && "inline-block max-w-48 truncate align-bottom")} title={label}>
      {children}
    </span>
  );
}
