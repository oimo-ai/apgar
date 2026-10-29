import { Link, useNavigate, useSearch } from "@tanstack/react-router";
import { Plus, TriangleAlert } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";

import { ApiError, apiFetch } from "@/api/client";
import { useAgents, useDemoRegression, useStatus } from "@/api/queries";
import type { AgentOut, ReleaseOut } from "@/api/types";
import { AddAgentModal } from "@/components/AddAgentModal";
import { AgentsEmpty } from "@/components/AgentsEmpty";
import { DataTable, type Column } from "@/components/DataTable";
import { Mono } from "@/components/Mono";
import { DemoBadge } from "@/components/DemoBadge";
import { DemoSeedingNotice } from "@/components/DemoSeedingNotice";
import { ErrorState, Loading } from "@/components/States";
import { Notice } from "@/components/ui/notice";
import { VerdictBadge } from "@/components/VerdictBadge";
import { demoAgentNames, findDemoRegression } from "@/lib/demo";
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
  const demoNames = useMemo(() => demoAgentNames(agents.data?.items ?? []), [agents.data]);
  // The demo agents show up while the worker still replays their releases. The
  // page opens a demo regression as soon as its verdict is final, and only the
  // first demo agent counts until then, so the page it opens does not depend on
  // which replay finishes first.
  const regression = useDemoRegression(demoNames[0], pendingSeed);
  const openRelease = useCallback(
    (release: ReleaseOut) =>
      void navigate({ to: "/agents/$agent/releases/$release", params: { agent: release.agent, release: release.release } }),
    [navigate],
  );

  useEffect(() => {
    if (pendingSeed && regression.data) {
      openRelease(regression.data);
    }
  }, [openRelease, pendingSeed, regression.data]);

  useEffect(() => {
    if (status.data?.demo_seeding) {
      sawSeeding.current = true;
      return;
    }
    if (pendingSeed && sawSeeding.current && status.data) {
      sawSeeding.current = false;
      void findDemoRegression(demoNames)
        .then((release) => (release ? openRelease(release) : setPendingSeed(false)))
        .catch(() => setPendingSeed(false));
    }
  }, [demoNames, openRelease, pendingSeed, status.data]);

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
  const empty = rows.length === 0;
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
        {empty ? null : (
          <button type="button" data-testid="add-agent-open" className="app-button-primary" onClick={() => setAdding(true)}>
            <Plus size={16} strokeWidth={2} aria-hidden="true" />
            Add agent
          </button>
        )}
      </div>
      {empty ? (
        <AgentsEmpty
          seeding={seeding}
          onAdd={() => setAdding(true)}
          onSeed={() => {
            setPendingSeed(true);
            void apiFetch("/api/v1/demo/seed", { method: "POST" })
              .then(() => status.refetch())
              .catch((error: unknown) => {
                setPendingSeed(false);
                toast.error(error instanceof ApiError ? error.message : "Seed failed");
              });
          }}
        />
      ) : (
        <div data-testid="agents-table" className="flex flex-col gap-4">
          {seeding ? (
            <DemoSeedingNotice />
          ) : rows.every((row) => row.is_demo) ? (
            <Notice testId="agents-demo-notice" title="These are demo agents">
              Their traces are generated. Add your own agent to watch its releases, and delete the demo agents in{" "}
              <Link to="/settings" search={{ tab: "agents" }}>
                Settings
              </Link>{" "}
              when you are done.
            </Notice>
          ) : null}
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
