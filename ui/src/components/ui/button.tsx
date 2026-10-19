import { Slot } from "@radix-ui/react-slot";
import { type ButtonHTMLAttributes } from "react";

import { cn } from "@/lib/utils";

export function Button({
  className,
  variant = "default",
  size = "md",
  asChild = false,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "default" | "outline" | "ghost" | "danger" | "destructive";
  size?: "md" | "sm";
  asChild?: boolean;
}) {
  const Comp = asChild ? Slot : "button";
  return (
    <Comp
      className={cn(
        "inline-flex shrink-0 cursor-pointer items-center justify-center gap-1.5 rounded-md border font-medium whitespace-nowrap disabled:cursor-not-allowed disabled:opacity-50",
        size === "md" ? "h-8 px-3 text-sm" : "h-7 px-2.5 text-xs",
        variant === "default" && "border-primary bg-primary text-primary-foreground hover:enabled:brightness-90",
        variant === "outline" && "border-input bg-card hover:enabled:bg-muted",
        variant === "ghost" && "border-transparent bg-transparent hover:enabled:bg-muted",
        variant === "danger" && "border-input bg-card text-fail hover:enabled:border-fail hover:enabled:bg-fail-bg",
        variant === "destructive" && "border-fail bg-fail text-primary-foreground hover:enabled:brightness-90",
        className,
      )}
      {...props}
    />
  );
}
