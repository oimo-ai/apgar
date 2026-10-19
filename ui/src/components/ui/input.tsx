import { ChevronDown } from "lucide-react";
import type { InputHTMLAttributes, ReactNode, SelectHTMLAttributes } from "react";

import { cn } from "@/lib/utils";

export function Input({ className, ...props }: InputHTMLAttributes<HTMLInputElement>) {
  return <input className={cn("field-control", className)} {...props} />;
}

export function Select({ className, ...props }: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <span className={cn("relative inline-flex min-w-36 align-middle", className)}>
      <select className="field-control w-full cursor-pointer appearance-none pr-8" {...props} />
      <ChevronDown
        size={14}
        strokeWidth={2}
        aria-hidden="true"
        className="pointer-events-none absolute top-1/2 right-2.5 -translate-y-1/2 text-muted-foreground"
      />
    </span>
  );
}

export function Suffixed({ suffix, children }: { suffix: string; children: ReactNode }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      {children}
      <span className="text-xs text-muted-foreground">{suffix}</span>
    </span>
  );
}
