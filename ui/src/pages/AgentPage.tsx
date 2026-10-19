import { Link, useNavigate, useParams } from "@tanstack/react-router";
import { Circle, CircleAlert, CircleCheck, SlidersHorizontal } from "lucide-react";
import type { ReactNode } from "react";

import { useAgent, useAgentReleases } from "@/api/queries";
import type { AgentOut, ReleaseOut } from "@/api/types";
import { AgentSyncStatus } from "@/components/AgentSyncStatus";
import { type Column, DataTable } from "@/components/DataTable";
import { DemoBadge } from "@/components/DemoBadge";
import { Mono } from "@/components/Mono";
import { MetricCoverage } from "@/components/MetricCoverage";
import { ErrorState, Loading } from "@/components/States";
import { TimeAgo } from "@/components/TimeAgo";
import { VerdictBadge } from "@/components/VerdictBadge";
import { Button } from "@/components/ui/button";
import { Notice } from "@/components/ui/notice";
import { Panel, PanelBody, PanelHeader } from "@/components/ui/panel";
import { formatCount } from "@/lib/format";
import { productLabel } from "@/lib/labels";
import { cn } from "@/lib/utils";


function filterSummary(agent: AgentOut): string {
  const filter = agent.filter;
  if (!filter) {
    return "";
  }
  const parts: string[] = [];
  if (filter.trace_name) {
    parts.push(`trace name is ${filter.trace_name}`);
  }
  for (const tag of filter.tags) {
    parts.push(`tag is ${tag}`);
  }
  for (const [key, value] of Object.entries(filter.metadata)) {
    parts.push(`metadata ${key} is ${value}`);
  }
  return parts.join(" and ");
}

type StepState = "done" | "pending" | "error";

function Step({ state, title, children }: { state: StepState; title: string; children: ReactNode }) {
  const Icon = state === "done" ? CircleCheck : state === "error" ? CircleAlert : Circle;
  return (
    <li className="flex gap-3">
      <Icon
        size={18}
        strokeWidth={2}
        aria-hidden="true"
        className={cn(
          "mt-0.5 shrink-0",
          state === "done" && "text-pass",
          state === "error" && "text-fail",
          state === "pending" && "text-muted-foreground",
        )}
      />
      <div className="min-w-0">
        <p className="m-0 font-medium">
          {title}
          <span className="sr-only">{state === "done" ? ", done" : state === "error" ? ", failed" : ", pending"}</span>
        </p>
        <div className="m-0 text-sm text-muted-foreground">{children}</div>
      </div>
    </li>
  );
}

function GettingStarted({ agent, hasReleases }: { agent: AgentOut; hasReleases: boolean }) {
  const langfuse = agent.source === "langfuse";
  const syncState: StepState =
    agent.sync?.status === "error" ? "error" : agent.sync?.last_success_at ? "done" : "pending";
  const turnsState: StepState = agent.activity.last_turn_at ? "done" : "pending";
  const releaseFrom = agent.release.from ?? "apgar.release, gen_ai.agent.version, or langfuse.release";
  const verdict = agent.effective_verdict;
  return (
    <Panel testId="agent-getting-started">
      <PanelHeader title="Getting started" description="This agent has no traffic yet. Apgar shows releases once turns arrive." />
      <PanelBody>
        <ol className="m-0 flex list-none flex-col gap-4 p-0">
          {langfuse ? (
            <Step state={syncState} title="Connect to Langfuse">
              {syncState === "done" ? (
                <>Last synced <TimeAgo iso={agent.sync?.last_success_at} />.</>
              ) : syncState === "error" ? (
                "The last sync failed. See the error above."
              ) : (
                "Waiting for the first sync. The connector runs every 60 seconds."
              )}
            </Step>
          ) : (
            <Step state={turnsState} title="Send spans">
              Point your exporter at <Mono>/v1/traces</Mono> with this agent&apos;s ingest token.
            </Step>
          )}
          <Step state={turnsState} title={langfuse ? "Match traces" : "Receive the first turn"}>
            {turnsState === "done" ? (
              <>Last turn <TimeAgo iso={agent.activity.last_turn_at} />.</>
            ) : langfuse ? (
              <>
                Waiting for traces where <Mono>{filterSummary(agent)}</Mono>. Langfuse can take a few minutes to make new
                traces available.
              </>
            ) : (
              "Waiting for the first turn."
            )}
          </Step>
          <Step state={hasReleases ? "done" : "pending"} title="Tag releases">
            Read from <Mono>{releaseFrom}</Mono>. Turns without it count as untagged.
          </Step>
          <Step state="pending" title="First verdict">
            Each release needs {formatCount(verdict.min_turns)} turns and {formatCount(verdict.min_sessions)} sessions,
            compared against the previous release.
          </Step>
        </ol>
      </PanelBody>
    </Panel>
  );
}

function ReleasesPanel({ agent, rows }: { agent: string; rows: ReleaseOut[] }) {
  const navigate = useNavigate();
  const columns: Column<ReleaseOut>[] = [
    {
      id: "release",
      header: "Release",
      sortValue: (row) => row.release,
      cell: (row) => (
        <Link to="/agents/$agent/releases/$release" params={{ agent, release: row.release }}>
          <Mono truncate>{row.release}</Mono>
        </Link>
      ),
    },
    { id: "first_seen", header: "First seen", sortValue: (row) => row.first_seen, cell: (row) => <TimeAgo iso={row.first_seen} /> },
    {
      id: "baseline",
      header: "Baseline",
      cell: (row) => (row.baseline.release ? <Mono truncate>{row.baseline.release}</Mono> : <span className="text-muted-foreground">none</span>),
    },
    { id: "turns", header: "Turns", numeric: true, sortValue: (row) => row.turn_count, cell: (row) => formatCount(row.turn_count) },
    {
      id: "verdict",
      header: "Verdict",
      sortValue: (row) => row.state,
      cell: (row) => <VerdictBadge state={row.state} reason={row.reason} final={row.final} early={row.early} />,
    },
  ];
  return (
    <section data-testid="agent-release-timeline" className="flex flex-col gap-2">
      <h3 className="m-0 text-base font-semibold">Releases</h3>
      {rows.length > 0 ? (
        <DataTable
          columns={columns}
          rows={rows}
          rowKey={(row) => row.release}
          rowTestId={(row) => `release-row-${row.release}`}
          onOpen={(row) => void navigate({ to: "/agents/$agent/releases/$release", params: { agent, release: row.release } })}
          caption="Releases"
        />
      ) : (
        <Panel>
          <PanelBody className="py-8 text-center text-sm text-muted-foreground">
            No releases yet. Releases appear once turns carry a release attribute.
          </PanelBody>
        </Panel>
      )}
    </section>
  );
}

export function AgentPage() {
  const { agent: name = "" } = useParams({ strict: false });
  const agent = useAgent(name);
  const releases = useAgentReleases(name);

  if ((agent.isPending && !agent.data) || (releases.isPending && !releases.data)) {
    return <Loading />;
  }
  if (!agent.data) {
    return <ErrorState error={agent.error} retry={() => void agent.refetch()} />;
  }
  const data = agent.data;
  const releaseRows = releases.data?.items ?? [];
  const empty = data.activity.turns_24h === 0 && releaseRows.length === 0;

  return (
    <div data-testid="page-agent" className="flex flex-col gap-4">
      <div className="page-head">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="page-title">{data.name}</h2>
            {data.is_demo ? <DemoBadge /> : null}
            <span className="pill">{productLabel(data.source)}</span>
            <span className="pill">{data.environment ?? "any environment"}</span>
          </div>
          <p className="page-sub">
            Release health for {data.source === "langfuse" ? "traces matched from Langfuse" : "spans sent over OTLP"}, compared
            release by release.
          </p>
        </div>
        <Button variant="outline" asChild>
          <Link to="/settings" search={{ tab: "agents", agent: data.name }}>
            <SlidersHorizontal size={14} strokeWidth={2} aria-hidden="true" />
            Configure
          </Link>
        </Button>
      </div>

      {data.warnings.includes("untagged_share") ? (
        <Notice tone="warning" testId="agent-untagged-warning">
          More than 5% of turns have no release. Set the release attribute on your spans.
        </Notice>
      ) : null}
      {data.warnings.includes("behavior_coverage") ? (
        <Notice tone="warning" testId="agent-coverage-warning">
          Fewer than half of the Behavior metrics are active, so changes in how the agent behaves can go unnoticed. Enable
          tool arguments and message content.
        </Notice>
      ) : null}
      {data.warnings.includes("multiple_environments") ? (
        <Notice tone="warning" testId="agent-env-warning">
          Turns from several environments are mixed in this agent's verdicts.{" "}
          <Link to="/settings" search={{ tab: "agents", agent: data.name, section: "general" }}>Set an environment</Link>
        </Notice>
      ) : null}

      <Panel testId="agent-coverage">
        <PanelBody>
          <MetricCoverage coverage={data.coverage} />
        </PanelBody>
      </Panel>

      <AgentSyncStatus source={data.source} sync={data.sync} />

      {empty ? (
        <GettingStarted agent={data} hasReleases={releaseRows.length > 0} />
      ) : (
        <ReleasesPanel agent={data.name} rows={releaseRows} />
      )}
    </div>
  );
}
