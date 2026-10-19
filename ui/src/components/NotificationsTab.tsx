import { RotateCw } from "lucide-react";
import { useState } from "react";

import { apiFetch } from "@/api/client";
import { useNotifications } from "@/api/queries";
import { Mono } from "@/components/Mono";
import { Pagination } from "@/components/Pagination";
import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/input";
import { Panel, PanelFooter, PanelHeader, TableEmpty } from "@/components/ui/panel";
import { StatusPill } from "@/components/ui/status-pill";
import { formatUtc } from "@/lib/format";

const FILTERS = ["failed", "pending", "sent", "all"] as const;
const PAGE_SIZE = 50;

export function NotificationsTab() {
  const [status, setStatus] = useState<(typeof FILTERS)[number]>("failed");
  const [offset, setOffset] = useState(0);
  const query = useNotifications(status, PAGE_SIZE, offset);
  const items = query.data?.items ?? [];
  const total = query.data?.total ?? 0;
  return (
    <Panel>
      <PanelHeader
        title="Notifications"
        description="Slack and webhook deliveries. Failed deliveries can be retried."
        actions={
          <label className="flex items-center gap-2 text-xs font-medium text-muted-foreground">
            Status
            <Select
              data-testid="notifications-filter-status"
              value={status}
              onChange={(event) => {
                setStatus(event.target.value as (typeof FILTERS)[number]);
                setOffset(0);
              }}
            >
              {FILTERS.map((item) => (
                <option key={item} value={item}>
                  {item}
                </option>
              ))}
            </Select>
          </label>
        }
      />
      <div className="overflow-x-auto">
        <table data-testid="notifications-table" className="data-table">
          <thead>
            <tr>
              <th>Created</th>
              <th>Agent</th>
              <th>Release</th>
              <th>Event</th>
              <th>Channel</th>
              <th>Status</th>
              <th className="text-right">Attempts</th>
              <th>Next attempt</th>
              <th>Last error</th>
              <th>
                <span className="sr-only">Actions</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {items.length === 0 ? <TableEmpty colSpan={10}>No {status === "all" ? "" : `${status} `}notifications.</TableEmpty> : null}
            {items.map((row) => {
              const error = row.last_error ?? "";
              const shown = error.length > 80 ? `${error.slice(0, 80)}…` : error;
              return (
                <tr key={row.id} data-testid={`notification-row-${row.id}`}>
                  <td className="whitespace-nowrap">{formatUtc(row.created_at)}</td>
                  <td className="font-medium">{row.agent}</td>
                  <td>
                    <Mono truncate>{row.release}</Mono>
                  </td>
                  <td>{row.event}</td>
                  <td>
                    <span className="pill">{row.channel}</span>
                  </td>
                  <td>
                    <StatusPill status={row.status} />
                  </td>
                  <td className="num text-right">{row.attempts}</td>
                  <td className="whitespace-nowrap">{row.next_attempt_at ? formatUtc(row.next_attempt_at) : ""}</td>
                  <td className="text-muted-foreground" title={error}>{shown}</td>
                  <td className="text-right">
                    {row.status === "failed" ? (
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        data-testid={`notification-retry-${row.id}`}
                        onClick={() => {
                          void apiFetch(`/api/v1/notifications/${row.id}/retry`, { method: "POST" })
                            .then(() => query.refetch())
                            .catch(() => undefined);
                        }}
                      >
                        <RotateCw size={12} strokeWidth={2} aria-hidden="true" />
                        Retry
                      </Button>
                    ) : null}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <PanelFooter>
        <Pagination offset={offset} limit={PAGE_SIZE} total={total} onOffset={setOffset} />
      </PanelFooter>
    </Panel>
  );
}
