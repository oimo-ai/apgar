import type { ReactNode } from "react";

import { ApiError } from "@/api/client";
import { Button } from "@/components/ui/button";

export function Loading() {
  return (
    <div data-testid="loading" role="status">
      Loading
    </div>
  );
}

export function EmptyState({ children }: { children: ReactNode }) {
  return (
    <div data-testid="empty-state" className="rounded-lg border border-border bg-card px-4 py-5">
      {children}
    </div>
  );
}

export function ErrorState({ error, retry }: { error: unknown; retry?: () => void }) {
  const message = error instanceof ApiError ? error.message : "Something went wrong";
  return (
    <div data-testid="error-state" role="alert" className="flex flex-col items-start gap-3 rounded-lg border border-l-4 border-border border-l-fail bg-fail-bg px-4 py-3 text-fail">
      <p>{message}</p>
      {retry ? (
        <Button type="button" variant="outline" onClick={retry}>
          Retry
        </Button>
      ) : null}
    </div>
  );
}
