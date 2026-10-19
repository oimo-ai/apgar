import { Check, Monitor, Moon, Sun } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { useTheme, type ThemeChoice } from "@/lib/theme";
import { cn } from "@/lib/utils";

const OPTIONS: { id: ThemeChoice; label: string; testId: string }[] = [
  { id: "light", label: "Light", testId: "theme-option-light" },
  { id: "dark", label: "Dark", testId: "theme-option-dark" },
  { id: "system", label: "System", testId: "theme-option-system" },
];

function ThemeGlyph({ choice }: { choice: ThemeChoice }) {
  const props = { size: 15, strokeWidth: 1.75, "aria-hidden": true as const };
  if (choice === "light") {
    return <Sun {...props} />;
  }
  if (choice === "dark") {
    return <Moon {...props} />;
  }
  return <Monitor {...props} />;
}

export function ThemeToggle({ variant = "button" }: { variant?: "button" | "status" }) {
  const { choice, setChoice } = useTheme();
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const current = OPTIONS.find((option) => option.id === choice) ?? OPTIONS[2];

  useEffect(() => {
    if (!open) {
      return;
    }
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setOpen(false);
      }
    }
    function onPointer(event: MouseEvent) {
      if (!rootRef.current?.contains(event.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("keydown", onKey);
    document.addEventListener("mousedown", onPointer);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("mousedown", onPointer);
    };
  }, [open]);

  return (
    <div className="relative" ref={rootRef}>
      <button
        type="button"
        data-testid="theme-toggle"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label="Theme"
        className={cn("rounded-md border border-border text-sm", variant === "status" ? "app-chip" : "px-2 py-1")}
        onClick={() => setOpen((value) => !value)}
      >
        {variant === "status" ? (
          <span className="inline-flex items-center gap-2">
            <ThemeGlyph choice={choice} />
            {current.label}
          </span>
        ) : (
          "Theme"
        )}
      </button>
      {open ? (
        <div role="menu" className="absolute right-0 z-20 mt-1.5 min-w-40 rounded-lg border border-border bg-card p-1 shadow-lg">
          {OPTIONS.map((option) => (
            <button
              key={option.id}
              type="button"
              role="menuitemradio"
              aria-checked={choice === option.id}
              data-testid={option.testId}
              className={cn(
                "flex w-full cursor-pointer items-center justify-between gap-3 rounded-sm px-2 py-1.5 text-left text-sm hover:bg-muted",
                choice === option.id && "bg-muted font-medium",
              )}
              onClick={() => {
                setChoice(option.id);
                setOpen(false);
              }}
            >
              {option.label}
              {choice === option.id ? <Check size={14} strokeWidth={2} aria-hidden="true" /> : null}
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}
