import * as Tooltip from "@radix-ui/react-tooltip";
import { Info } from "lucide-react";
import type { ReactElement, ReactNode } from "react";

export function Tip({ content, children }: { content: ReactNode; children: ReactElement }) {
  return (
    <Tooltip.Provider delayDuration={100}>
      <Tooltip.Root>
        <Tooltip.Trigger asChild>{children}</Tooltip.Trigger>
        <Tooltip.Portal>
          <Tooltip.Content
            side="top"
            sideOffset={6}
            className="z-50 max-w-72 rounded-md bg-foreground px-2.5 py-1.5 text-xs leading-snug text-background shadow-lg"
          >
            {content}
            <Tooltip.Arrow className="fill-foreground" />
          </Tooltip.Content>
        </Tooltip.Portal>
      </Tooltip.Root>
    </Tooltip.Provider>
  );
}

export function ReasonTip({ reason, children }: { reason: string | null | undefined; children: ReactNode }) {
  if (!reason) {
    return <>{children}</>;
  }
  return (
    <Tooltip.Provider delayDuration={150}>
      <Tooltip.Root>
        <Tooltip.Trigger asChild>
          <span tabIndex={0} className="inline-flex rounded-md [&>:disabled]:pointer-events-none">
            {children}
          </span>
        </Tooltip.Trigger>
        <Tooltip.Portal>
          <Tooltip.Content
            side="top"
            sideOffset={6}
            className="z-50 max-w-72 rounded-md bg-foreground px-2.5 py-1.5 text-xs leading-snug text-background shadow-lg"
          >
            {reason}
            <Tooltip.Arrow className="fill-foreground" />
          </Tooltip.Content>
        </Tooltip.Portal>
      </Tooltip.Root>
    </Tooltip.Provider>
  );
}

export function InfoTip({ label, children }: { label: string; children: ReactNode }) {
  return (
    <Tooltip.Provider delayDuration={150}>
      <Tooltip.Root>
        <Tooltip.Trigger asChild>
          <button
            type="button"
            aria-label={`About ${label}`}
            className="inline-grid size-4 cursor-help place-items-center rounded-full text-muted-foreground hover:text-foreground"
          >
            <Info size={13} strokeWidth={2} aria-hidden="true" />
          </button>
        </Tooltip.Trigger>
        <Tooltip.Portal>
          <Tooltip.Content
            side="top"
            sideOffset={6}
            className="z-50 max-w-72 rounded-md bg-foreground px-2.5 py-1.5 text-xs leading-snug text-background shadow-lg"
          >
            {children}
            <Tooltip.Arrow className="fill-foreground" />
          </Tooltip.Content>
        </Tooltip.Portal>
      </Tooltip.Root>
    </Tooltip.Provider>
  );
}
