import { type ReactNode, useCallback, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { Modal, ModalBody, ModalFooter } from "@/components/ui/modal";

interface ConfirmOptions {
  title: string;
  description?: ReactNode;
  confirmLabel?: string;
  tone?: "danger" | "default";
}

export function useConfirm(): { confirm: (options: ConfirmOptions) => Promise<boolean>; dialog: ReactNode } {
  const [options, setOptions] = useState<ConfirmOptions | null>(null);
  const resolver = useRef<((value: boolean) => void) | null>(null);

  const settle = useCallback((value: boolean) => {
    resolver.current?.(value);
    resolver.current = null;
    setOptions(null);
  }, []);

  const confirm = useCallback((next: ConfirmOptions) => {
    resolver.current?.(false);
    setOptions(next);
    return new Promise<boolean>((resolve) => {
      resolver.current = resolve;
    });
  }, []);

  const dialog = (
    <Modal
      open={options !== null}
      onOpenChange={(open) => {
        if (!open) {
          settle(false);
        }
      }}
      title={options?.title ?? ""}
      size="sm"
      testId="confirm-dialog"
    >
      {options?.description ? <ModalBody className="text-sm">{options.description}</ModalBody> : null}
      <ModalFooter>
        <Button type="button" variant="outline" data-testid="confirm-cancel" onClick={() => settle(false)}>
          Cancel
        </Button>
        <Button
          type="button"
          variant={options?.tone === "default" ? "default" : "destructive"}
          data-testid="confirm-accept"
          data-autofocus
          onClick={() => settle(true)}
        >
          {options?.confirmLabel ?? "Confirm"}
        </Button>
      </ModalFooter>
    </Modal>
  );

  return { confirm, dialog };
}
