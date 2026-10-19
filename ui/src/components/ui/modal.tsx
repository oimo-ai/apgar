import * as Dialog from "@radix-ui/react-dialog";
import { X } from "lucide-react";
import { type ReactNode, useRef } from "react";

import { cn } from "@/lib/utils";

export function Modal({
  open,
  onOpenChange,
  title,
  description,
  size = "md",
  testId,
  children,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description?: ReactNode;
  size?: "sm" | "md" | "lg";
  testId?: string;
  children: ReactNode;
}) {
  const returnFocus = useRef<HTMLElement | null>(null);
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-black/45" />
        <Dialog.Content
          data-testid={testId}
          onOpenAutoFocus={(event) => {
            returnFocus.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
            const preferred = (event.currentTarget as HTMLElement).querySelector<HTMLElement>("[data-autofocus]");
            if (preferred) {
              event.preventDefault();
              preferred.focus();
            }
          }}
          onCloseAutoFocus={(event) => {
            // Radix only returns focus to a Dialog.Trigger, and these modals open from plain buttons.
            const target = returnFocus.current;
            returnFocus.current = null;
            if (target?.isConnected) {
              event.preventDefault();
              target.focus();
            }
          }}
          className={cn(
            "fixed top-1/2 left-1/2 z-50 flex max-h-[min(44rem,calc(100vh-2rem))] w-[calc(100%-2rem)] -translate-x-1/2 -translate-y-1/2 flex-col rounded-lg border border-border bg-card shadow-xl",
            size === "sm" && "max-w-[28rem]",
            size === "md" && "max-w-[32rem]",
            size === "lg" && "max-w-[42rem]",
          )}
        >
          <div className="flex items-start justify-between gap-4 border-b border-border px-5 py-4">
            <div className="min-w-0">
              <Dialog.Title className="m-0 text-base font-semibold">{title}</Dialog.Title>
              {description ? (
                <Dialog.Description className="m-0 mt-1 text-sm text-muted-foreground">{description}</Dialog.Description>
              ) : (
                <Dialog.Description className="sr-only">{title}</Dialog.Description>
              )}
            </div>
            <Dialog.Close
              aria-label="Close"
              className="-mt-1 -mr-1 inline-grid size-7 shrink-0 cursor-pointer place-items-center rounded-md text-muted-foreground hover:bg-muted hover:text-foreground"
            >
              <X size={16} strokeWidth={2} aria-hidden="true" />
            </Dialog.Close>
          </div>
          {children}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

export function ModalBody({ className, children }: { className?: string; children: ReactNode }) {
  return <div className={cn("min-h-0 flex-1 overflow-y-auto px-5 py-4", className)}>{children}</div>;
}

export function ModalFooter({ children }: { children: ReactNode }) {
  return (
    <div className="flex flex-wrap items-center justify-end gap-2 rounded-b-lg border-t border-border bg-muted px-5 py-3">
      {children}
    </div>
  );
}
