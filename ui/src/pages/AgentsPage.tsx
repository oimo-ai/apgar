import { Link, useNavigate, useSearch } from "@tanstack/react-router";
import { Plus, TriangleAlert } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import { ApiError, apiFetch } from "@/api/client";
import { useAgents, useStatus } from "@/api/queries";
import type { AgentOut } from "@/api/types";
import { AddAgentModal } from "@/components/AddAgentModal";
import { DataTable, type Column } from "@/components/DataTable";
import { Mono } from "@/components/Mono";
import { DemoBadge } from "@/components/DemoBadge";
import { EmptyState, ErrorState, Loading } from "@/components/States";
import { VerdictBadge } from "@/components/VerdictBadge";
import { formatCount } from "@/lib/format";
import { productLabel, warningLabel } from "@/lib/labels";

export function AgentsPage() {
  const navigate = useNavigate();
  const search = useSearch({ from: "/authed/" });
  const adding = search.add === true;
  const setAdding = (next: boolean) => void navigate({ to: "/", search: next ? { add: true } : {}, replace: true });
  const status = useStatus();
  const [pendingSeed, setPendingSeed] = useState(false);
  const sawSeeding = useRef(false);
  const seeding = pendingSeed || Boolean(status.data?.demo_seeding);
  const agents = useAgents(seeding);

  useEffect(() => {
    if (status.data?.demo_seeding) {
      sawSeeding.current = true;
    }
    if (pendingSeed && sawSeeding.current && status.data && !status.data.demo_seeding) {
      sawSeeding.current = false;
      setPendingSeed(false);
    }
  }, [pendingSeed, status.data]);

  if (agents.isPending && !agents.data) {
    return <Loading />;
  }
  if (agents.isError && !agents.data) {
    return <ErrorState error={agents.error} retry={() => void agents.refetch()} />;
  }
  if (!agents.data) {
    return <Loading />;
  }

  const rows = agents.data.items;
  const columns: Column<AgentOut>[] = [
    {
      id: "name",
      header: "Name",
      sortValue: (row) => row.name,
      cell: (row) => (
        <span className="inline-flex items-center gap-2">
          <Link to="/agents/$agent" params={{ agent: row.name }}>
            {row.name}
          </Link>
          {row.is_demo ? <DemoBadge /> : null}
        </span>
      ),
    },
    { id: "source", header: "Source", sortValue: (row) => row.source, cell: (row) => productLabel(row.source) },
    {
      id: "environment",
      header: "Environment",
      sortValue: (row) => row.environment ?? "",
      cell: (row) => row.environment ?? "any",
    },
    {
      id: "latest",
      header: "Latest release",
      cell: (row) =>
        row.latest_release ? (
          <span className="inline-flex items-center gap-2">
            <Mono truncate>{row.latest_release.release}</Mono>
            <span data-testid={`agent-latest-verdict-${row.name}`} data-state={row.latest_release.state}>
              <VerdictBadge
                state={row.latest_release.state}
                reason={row.latest_release.reason}
                final={row.latest_release.final}
                early={row.latest_release.early}
              />
            </span>
          </span>
        ) : (
          "n/a"
        ),
    },
    {
      id: "turns",
      header: "Turns 24h",
      numeric: true,
      sortValue: (row) => row.activity.turns_24h,
      cell: (row) => formatCount(row.activity.turns_24h),
    },
    {
      id: "coverage",
      header: "Metrics",
      numeric: true,
      sortValue: (row) => row.coverage?.active ?? -1,
      cell: (row) => (
        <span data-testid={`agent-coverage-${row.name}`}>
          {row.coverage ? `${row.coverage.active} of ${row.coverage.total} active` : "n/a"}
        </span>
      ),
    },
    {
      id: "warning",
      header: "Setup",
      cell: (row) =>
        row.warnings.length > 0 ? (
          <Link
            data-testid={`agent-warning-${row.name}`}
            to="/agents/$agent"
            params={{ agent: row.name }}
            title={row.warnings.map(warningLabel).join("\n")}
            className="inline-flex items-center gap-1 text-inconclusive"
          >
            <TriangleAlert size={14} aria-hidden="true" />
            {row.warnings.length === 1 ? warningLabel(row.warnings[0]) : `${row.warnings.length} warnings`}
          </Link>
        ) : null,
    },
  ];

  return (
    <div data-testid="page-agents" className="flex flex-col gap-4">
      <div className="page-head">
        <div>
          <h2 className="page-title">Agents</h2>
          <p className="page-sub">Each agent with its latest release verdict against the baseline.</p>
        </div>
        <button type="button" data-testid="add-agent-open" className="app-button-primary" onClick={() => setAdding(true)}>
          <Plus size={16} strokeWidth={2} aria-hidden="true" />
          Add agent
        </button>
      </div>
      {rows.length === 0 ? (
        <div data-testid="agents-empty">
          <EmptyState>
            <ol className="list-decimal pl-5">
              <li>Create an ingest token in Settings.</li>
              <li>Point an exporter at /v1/traces.</li>
              <li>Or connect Langfuse.</li>
            </ol>
            <p className="mt-2">
              <button type="button" className="cursor-pointer border-0 bg-transparent p-0 text-primary hover:underline" onClick={() => setAdding(true)}>
                Add agent
              </button>
            </p>
          </EmptyState>
          <button
            type="button"
            data-testid="seed-demo-button"
            className="app-chip mt-3"
            disabled={seeding}
            onClick={() => {
              setPendingSeed(true);
              void apiFetch("/api/v1/demo/seed", { method: "POST" }).catch((error: unknown) => {
                setPendingSeed(false);
                toast.error(error instanceof ApiError ? error.message : "Seed failed");
              });
            }}
          >
            Seed demo data
          </button>
          {seeding ? <p>Seeding demo data, this takes about two minutes</p> : null}
        </div>
      ) : (
        <div data-testid="agents-table">
          <DataTable
            columns={columns}
            rows={rows}
            rowKey={(row) => row.name}
            rowTestId={(row) => `agent-row-${row.name}`}
            onOpen={(row) => void navigate({ to: "/agents/$agent", params: { agent: row.name } })}
          />
        </div>
      )}
      <AddAgentModal open={adding} onOpenChange={setAdding} onCreated={() => void agents.refetch()} />
    </div>
  );
}
