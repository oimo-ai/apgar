import { ChevronRight } from "lucide-react";
import { useState, type ReactNode } from "react";
import { cn } from "@/lib/utils";

/**
 * A collapsible group of rows inside a table. Renders its own <tbody>, so use one per group.
 * The first cell of each row must be a <td>; it is indented to line up with the group title.
 */
export function TableGroup({
  title,
  meta,
  colSpan,
  defaultOpen = true,
  testId,
  children,
}: {
  title: string;
  meta?: ReactNode;
  colSpan: number;
  defaultOpen?: boolean;
  testId?: string;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <tbody data-testid={testId} className="border-t border-border [&>tr>td:first-child]:pl-10">
      <tr>
        <th colSpan={colSpan} scope="colgroup" className="bg-muted/50 px-2 py-1.5 text-left font-normal">
          <button
            type="button"
            aria-expanded={open}
            onClick={() => setOpen(!open)}
            className="flex items-center gap-2 rounded-md px-2 py-1 text-sm font-semibold text-foreground hover:bg-muted focus-visible:outline-2 focus-visible:outline-ring"
          >
            <ChevronRight aria-hidden className={cn("size-4 text-muted-foreground transition-transform", open && "rotate-90")} />
            {title}
            {meta}
          </button>
        </th>
      </tr>
      {open ? children : null}
    </tbody>
  );
}
