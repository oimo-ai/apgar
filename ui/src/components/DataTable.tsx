import { type ReactNode, useState } from "react";

import { cn } from "@/lib/utils";

export interface Column<T> {
  id: string;
  header: string;
  numeric?: boolean;
  sortValue?: (row: T) => string | number | null;
  cell: (row: T) => ReactNode;
}

export function DataTable<T>({
  columns,
  rows,
  rowKey,
  rowTestId,
  onOpen,
  caption,
}: {
  columns: Column<T>[];
  rows: T[];
  rowKey: (row: T) => string;
  rowTestId?: (row: T) => string;
  onOpen?: (row: T) => void;
  caption?: string;
}) {
  const [sort, setSort] = useState<{ id: string; dir: "asc" | "desc" } | null>(null);
  const sorted = [...rows];
  if (sort) {
    const column = columns.find((item) => item.id === sort.id);
    if (column?.sortValue) {
      sorted.sort((a, b) => {
        const left = column.sortValue?.(a) ?? "";
        const right = column.sortValue?.(b) ?? "";
        const cmp = left < right ? -1 : left > right ? 1 : 0;
        return sort.dir === "asc" ? cmp : -cmp;
      });
    }
  }
  function fromControl(target: EventTarget | null): boolean {
    return target instanceof Element && Boolean(target.closest("a, button, input, select, textarea, label"));
  }
  return (
    <div className="overflow-x-auto rounded-lg border border-border bg-card">
      <table className="w-full border-collapse text-sm">
        {caption ? <caption className="sr-only">{caption}</caption> : null}
        <thead className="border-b border-border text-left text-xs text-muted-foreground">
          <tr>
            {columns.map((column) => {
              const active = sort?.id === column.id;
              const aria = active ? (sort.dir === "asc" ? "ascending" : "descending") : "none";
              return (
                <th key={column.id} aria-sort={aria} className={column.numeric ? "num text-right" : undefined}>
                  <button
                    type="button"
                    className={cn("w-full cursor-pointer whitespace-nowrap px-3 py-2 font-medium hover:text-foreground", column.numeric ? "text-right" : "text-left")}
                    onClick={() => {
                      if (!column.sortValue) {
                        return;
                      }
                      setSort((current) => {
                        if (current?.id !== column.id) {
                          return { id: column.id, dir: "asc" };
                        }
                        return { id: column.id, dir: current.dir === "asc" ? "desc" : "asc" };
                      });
                    }}
                  >
                    {column.header}
                  </button>
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody>
          {sorted.map((row) => (
            <tr
              key={rowKey(row)}
              data-testid={rowTestId?.(row)}
              tabIndex={0}
              className="cursor-pointer border-t border-border/60 first:border-t-0 hover:bg-muted focus-visible:bg-muted"
              onClick={(event) => {
                if (fromControl(event.target)) {
                  return;
                }
                onOpen?.(row);
              }}
              onKeyDown={(event) => {
                if (event.key !== "Enter" || fromControl(event.target)) {
                  return;
                }
                event.preventDefault();
                onOpen?.(row);
              }}
            >
              {columns.map((column) => (
                <td key={column.id} className={column.numeric ? "num whitespace-nowrap px-3 py-2.5 text-right" : "px-3 py-2.5"}>
                  {column.cell(row)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
