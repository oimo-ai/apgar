import { ChevronLeft, ChevronRight } from "lucide-react";

import { Button } from "@/components/ui/button";

export function Pagination({
  offset,
  limit,
  total,
  onOffset,
}: {
  offset: number;
  limit: number;
  total: number;
  onOffset: (offset: number) => void;
}) {
  return (
    <div className="flex w-full items-center justify-between gap-3">
      <span data-testid="pagination-range" className="text-xs text-muted-foreground">
        <span className="num font-medium text-foreground">
          {total === 0 ? 0 : offset + 1}–{Math.min(offset + limit, total)}
        </span>{" "}
        of <span className="num font-medium text-foreground">{total}</span>
      </span>
      {total > limit ? (
        <div className="flex items-center gap-2">
          <Button
            type="button"
            variant="outline"
            size="sm"
            data-testid="pagination-prev"
            disabled={offset <= 0}
            onClick={() => onOffset(Math.max(0, offset - limit))}
          >
            <ChevronLeft size={14} strokeWidth={2} aria-hidden="true" />
            Previous
          </Button>
          <Button
            type="button"
            variant="outline"
            size="sm"
            data-testid="pagination-next"
            disabled={offset + limit >= total}
            onClick={() => onOffset(offset + limit)}
          >
            Next
            <ChevronRight size={14} strokeWidth={2} aria-hidden="true" />
          </Button>
        </div>
      ) : null}
    </div>
  );
}
