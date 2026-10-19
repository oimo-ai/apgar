import { useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { Activity, Check, Filter, Scale, SlidersHorizontal, Trash2, TriangleAlert } from "lucide-react";
import { type ReactNode, useEffect, useState } from "react";
import { toast } from "sonner";

import { ApiError, apiFetch } from "@/api/client";
import { useAgents, useConnections } from "@/api/queries";
import type { AgentOut, MetricSettings, VerdictSettings } from "@/api/types";
import { Mono } from "@/components/Mono";
import { MetricCoverage } from "@/components/MetricCoverage";
import { ErrorState, Loading } from "@/components/States";
import { type Condition, conditionError, fromFilter, toFilter, TraceConditions } from "@/components/TraceConditions";
import { Button } from "@/components/ui/button";
import { useConfirm } from "@/components/ui/confirm";
import { Field, FieldError } from "@/components/ui/field";
import { Input, Select, Suffixed } from "@/components/ui/input";
import { Panel, PanelBody, PanelFooter, PanelHeader } from "@/components/ui/panel";
import { Switch } from "@/components/ui/switch";
import { productLabel } from "@/lib/labels";
import { TableGroup } from "@/components/ui/table-group";
import { InfoTip } from "@/components/ui/tooltip";
import { METRIC_GROUPS, metricDescription, metricLabel } from "@/lib/metrics";
import { RELEASE_OPTIONS, releaseChoice, releaseValue } from "@/lib/releaseAttributes";
import { cn } from "@/lib/utils";

export type AgentSection = "general" | "source" | "metrics" | "verdict" | "danger";

const SECTIONS: { id: AgentSection; label: string; Icon: typeof Activity; langfuseOnly?: boolean }[] = [
  { id: "general", label: "General", Icon: SlidersHorizontal },
  { id: "source", label: "Trace selection", Icon: Filter, langfuseOnly: true },
  { id: "metrics", label: "Metrics", Icon: Activity },
  { id: "verdict", label: "Verdict rules", Icon: Scale },
  { id: "danger", label: "Danger zone", Icon: TriangleAlert },
];

const VERDICT_GROUPS: { title: string; fields: (keyof VerdictSettings)[] }[] = [
  { title: "Sample size", fields: ["min_turns", "min_sessions", "min_turns_slice"] },
  { title: "Confirmation and monitoring", fields: ["fail_confirmations", "pass_confirmations", "max_window_hours"] },
  { title: "Notifications", fields: ["notify_healthy"] },
  { title: "Mixed sessions", fields: ["include_mixed_sessions"] },
];

// Matches VerdictSettings.alpha in apgar/domain/settings.py.
const DEFAULT_ALPHA = 0.05;

const VERDICT_LABELS: Record<string, string> = {
  min_turns: "Minimum turns",
  min_sessions: "Minimum sessions",
  min_turns_slice: "Minimum turns per slice",
  fail_confirmations: "FAIL confirmations",
  pass_confirmations: "PASS confirmations",
  max_window_hours: "Monitor each release for up to",
  notify_healthy: "Send the healthy message",
  include_mixed_sessions: "Include mixed sessions",
};

const VERDICT_INFO: Record<string, string> = {
  min_turns: "Turns the candidate and the baseline each need before a release can be called healthy. Default 200.",
  min_sessions: "Sessions the candidate needs before a release can be called healthy. Default 30.",
  min_turns_slice: "Turns a slice needs on both sides before it is evaluated. Default 100.",
  fail_confirmations: "Consecutive failing evaluations, at least 10 minutes apart, that confirm FAIL. Default 2.",
  pass_confirmations: "Consecutive passing evaluations, at least 10 minutes apart, that confirm PASS. Default 2.",
  max_window_hours:
    "Ends earlier when a newer release gets traffic. A release that misses the minimum sample in time cannot become healthy. 1 to 168 hours, default 72.",
  notify_healthy: "Send a Slack message when a release becomes healthy. On by default.",
  include_mixed_sessions: "Keep sessions that span both releases in the comparison. Off by default.",
};

const VERDICT_SUFFIX: Record<string, string> = { max_window_hours: "hours" };

function verdictError(field: keyof VerdictSettings, value: unknown): string {
  if (typeof value !== "number") {
    return "";
  }
  if (Number.isNaN(value)) {
    return "Enter a number.";
  }
  if (field === "max_window_hours") {
    return Number.isInteger(value) && value >= 1 && value <= 168 ? "" : "Use a whole number of hours between 1 and 168.";
  }
  return Number.isInteger(value) && value >= 1 ? "" : "Use a whole number of at least 1.";
}

function failToast(error: unknown, fallback = "Save failed"): void {
  toast.error(error instanceof ApiError ? error.message : fallback);
}

function same(left: unknown, right: unknown): boolean {
  return JSON.stringify(left) === JSON.stringify(right);
}

export function AgentSettings({
  agentName,
  section,
  onNavigate,
}: {
  agentName: string | undefined;
  section: string | undefined;
  onNavigate: (next: { agent?: string; section?: AgentSection }) => void;
}) {
  const agents = useAgents();
  const { confirm, dialog } = useConfirm();
  const [dirty, setDirty] = useState(false);

  useEffect(() => {
    if (!dirty) {
      return;
    }
    const warn = (event: BeforeUnloadEvent) => event.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  if (agents.isPending && !agents.data) {
    return <Loading />;
  }
  if (!agents.data) {
    return <ErrorState error={agents.error} retry={() => void agents.refetch()} />;
  }
  const items = agents.data.items;
  if (items.length === 0) {
    return (
      <Panel>
        <PanelBody className="flex flex-col items-center gap-3 py-10 text-center">
          <p className="m-0 text-sm text-muted-foreground">No agents yet. Add one to configure its verdict rules.</p>
          <Button asChild variant="outline">
            <Link to="/" search={{ add: true }}>Add agent</Link>
          </Button>
        </PanelBody>
      </Panel>
    );
  }
  const agent = items.find((item) => item.name === agentName) ?? items[0];
  const visible = SECTIONS.filter((item) => !item.langfuseOnly || agent.source === "langfuse");
  const active = visible.find((item) => item.id === section)?.id ?? "general";

  async function go(next: { agent?: string; section?: AgentSection }) {
    if (dirty) {
      const ok = await confirm({
        title: "Discard unsaved changes?",
        description: "Changes in this section have not been saved.",
        confirmLabel: "Discard changes",
      });
      if (!ok) {
        return;
      }
      setDirty(false);
    }
    onNavigate(next);
  }

  return (
    <div data-testid="agent-settings-form" className="flex flex-col gap-4">
      <Panel>
        <div className="flex flex-wrap items-center gap-x-4 gap-y-3 px-4 py-3">
          <div className="flex min-w-0 flex-col gap-1">
            <label htmlFor="agent-settings-select" className="text-xs text-muted-foreground">
              Configuring agent
            </label>
            <Select
              id="agent-settings-select"
              data-testid="agent-settings-select"
              className="min-w-64 font-mono font-semibold"
              value={agent.name}
              onChange={(event) => void go({ agent: event.target.value, section: active })}
            >
              {items.map((item) => (
                <option key={item.name} value={item.name}>
                  {item.name}
                </option>
              ))}
            </Select>
          </div>
          <div className="flex flex-wrap items-center gap-2 self-end pb-1.5">
            <span className="pill">{productLabel(agent.source)}</span>
            <span className="pill">{agent.environment ? agent.environment : "any environment"}</span>
            {agent.is_demo ? <span className="pill">demo</span> : null}
          </div>
          <Link to="/agents/$agent" params={{ agent: agent.name }} className="ml-auto self-end pb-1.5 text-sm">
            Open agent
          </Link>
        </div>
      </Panel>

      <div className="grid gap-6 md:grid-cols-[12rem_minmax(0,1fr)]">
        <nav aria-label="Agent settings" className="flex gap-1 overflow-x-auto md:sticky md:top-20 md:flex-col md:self-start">
          {visible.map(({ id, label, Icon }) => {
            const current = id === active;
            return (
              <button
                key={id}
                type="button"
                data-testid={`agent-settings-nav-${id}`}
                aria-current={current ? "page" : undefined}
                className={cn(
                  "flex shrink-0 cursor-pointer items-center gap-2 rounded-md border-l-2 px-3 py-1.5 text-left text-sm whitespace-nowrap",
                  current
                    ? "border-l-primary bg-muted font-medium text-foreground"
                    : "border-l-transparent text-muted-foreground hover:bg-muted hover:text-foreground",
                  id === "danger" && !current && "text-fail hover:text-fail",
                )}
                onClick={() => void go({ agent: agent.name, section: id })}
              >
                <Icon size={15} strokeWidth={2} aria-hidden="true" />
                {label}
                {current && dirty ? (
                  <span className="ml-auto size-2 rounded-full bg-inconclusive" aria-label="Unsaved changes" />
                ) : null}
              </button>
            );
          })}
        </nav>

        <div className="min-w-0">
          {active === "general" ? <GeneralSection key={agent.name} agent={agent} onDirty={setDirty} /> : null}
          {active === "source" ? <SourceSection key={agent.name} agent={agent} onDirty={setDirty} /> : null}
          {active === "metrics" ? <MetricsSection key={agent.name} agent={agent} onDirty={setDirty} /> : null}
          {active === "verdict" ? <VerdictSection key={agent.name} agent={agent} onDirty={setDirty} /> : null}
          {active === "danger" ? (
            <DangerSection
              agent={agent}
              onDeleted={() => {
                setDirty(false);
                onNavigate({ agent: undefined, section: undefined });
              }}
            />
          ) : null}
        </div>
      </div>
      {dialog}
    </div>
  );
}

function useSection<T>(
  agent: AgentOut,
  read: (agent: AgentOut) => T,
  onDirty: (dirty: boolean) => void,
  comparable: (value: T) => unknown = (value) => value,
) {
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState<T>(() => read(agent));
  const [base, setBase] = useState<T>(() => read(agent));
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const dirty = !same(comparable(draft), comparable(base));

  useEffect(() => {
    onDirty(dirty);
  }, [dirty, onDirty]);
  useEffect(() => () => onDirty(false), [onDirty]);

  async function save(body: Record<string, unknown>) {
    setSaving(true);
    try {
      const updated = await apiFetch<AgentOut>(`/api/v1/agents/${encodeURIComponent(agent.name)}`, {
        method: "PATCH",
        body: JSON.stringify(body),
      });
      const next = read(updated);
      setBase(next);
      setDraft(next);
      setSaved(true);
      toast("Agent settings saved");
      void queryClient.invalidateQueries({ queryKey: ["agents"] });
      void queryClient.invalidateQueries({ queryKey: ["agent", agent.name] });
    } catch (error) {
      failToast(error);
    } finally {
      setSaving(false);
    }
  }

  return {
    draft,
    setDraft: (next: T) => {
      setSaved(false);
      setDraft(next);
    },
    dirty,
    saving,
    saved: saved && !dirty,
    discard: () => setDraft(base),
    save,
  };
}

function SectionForm({
  title,
  description,
  dirty,
  saving,
  saved,
  invalid = false,
  onSave,
  onDiscard,
  children,
}: {
  title: string;
  description: string;
  dirty: boolean;
  saving: boolean;
  saved: boolean;
  invalid?: boolean;
  onSave: () => void;
  onDiscard: () => void;
  children: ReactNode;
}) {
  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        if (dirty && !invalid) {
          onSave();
        }
      }}
    >
      <Panel>
        <PanelHeader title={title} description={description} />
        {children}
        <PanelFooter>
          <span className="mr-auto text-sm">
            {saved ? (
              <span data-testid="agent-settings-saved" className="inline-flex items-center gap-1.5 text-pass">
                <Check size={14} strokeWidth={2} aria-hidden="true" />
                Saved
              </span>
            ) : dirty ? (
              <span data-testid="agent-settings-dirty" className="inline-flex items-center gap-1.5 text-muted-foreground">
                <span className="size-2 rounded-full bg-inconclusive" aria-hidden="true" />
                Unsaved changes
              </span>
            ) : null}
          </span>
          <Button type="button" variant="outline" disabled={!dirty || saving} onClick={onDiscard}>
            Discard
          </Button>
          <Button type="submit" data-testid="agent-settings-save" disabled={!dirty || saving || invalid}>
            {saving ? "Saving" : "Save"}
          </Button>
        </PanelFooter>
      </Panel>
    </form>
  );
}

function readGeneral(agent: AgentOut) {
  const release = releaseChoice(agent.release.from ?? "");
  return {
    environment: agent.environment ?? "",
    release_choice: release.choice,
    release_custom: release.custom,
    surface_from: agent.surface_mapping.from ?? "",
    output_format: agent.output_format,
    slack_connection: agent.slack_connection ?? "",
  };
}

function GeneralSection({ agent, onDirty }: { agent: AgentOut; onDirty: (dirty: boolean) => void }) {
  const connections = useConnections();
  const state = useSection(agent, readGeneral, onDirty, ({ release_choice, release_custom, ...rest }) => ({
    ...rest,
    release_from: releaseValue(release_choice, release_custom),
  }));
  const { draft } = state;
  const set = (patch: Partial<typeof draft>) => state.setDraft({ ...draft, ...patch });
  const slack = (connections.data?.items ?? []).filter((item) => item.type === "slack");
  const customRelease = draft.release_choice === "custom";
  const releaseInvalid = customRelease && draft.release_custom.trim() === "";
  return (
    <SectionForm
      title="General"
      description="How Apgar reads this agent's telemetry and where it reports."
      dirty={state.dirty}
      saving={state.saving}
      saved={state.saved}
      invalid={releaseInvalid}
      onDiscard={state.discard}
      onSave={() =>
        void state.save({
          environment: draft.environment.trim() || null,
          release: { from: releaseValue(draft.release_choice, draft.release_custom) || null },
          surface_mapping: { from: draft.surface_from.trim() || null },
          output_format: draft.output_format,
          slack_connection: draft.slack_connection || null,
        })
      }
    >
      <PanelBody className="flex flex-col gap-6">
        <fieldset className="m-0 grid gap-4 border-0 p-0 sm:grid-cols-2">
          <legend className="mb-3 p-0 text-xs font-semibold text-muted-foreground">Telemetry</legend>
          <Field label="Environment" htmlFor="agent-env" info="Only turns from this environment count toward verdicts. Empty accepts every environment.">
            <Input id="agent-env" data-testid="agent-setting-environment" placeholder="production" value={draft.environment} onChange={(event) => set({ environment: event.target.value })} />
          </Field>
          <Field label="Release attribute" htmlFor="agent-release" info="Span or resource attribute that carries the release identifier.">
            <Select id="agent-release" className="w-full" data-testid="agent-setting-release-from" value={draft.release_choice} onChange={(event) => set({ release_choice: event.target.value })}>
              <option value="" disabled>Select an attribute</option>
              {RELEASE_OPTIONS.map(([value, label]) => (
                <option key={value} value={value}>{label}</option>
              ))}
            </Select>
          </Field>
          {customRelease ? (
            <Field label="Custom attribute" htmlFor="agent-release-custom" required>
              <Input
                id="agent-release-custom"
                data-testid="agent-setting-release-custom"
                aria-required="true"
                className="font-mono"
                autoComplete="off"
                spellCheck={false}
                placeholder="my.release.attribute"
                value={draft.release_custom}
                onChange={(event) => set({ release_custom: event.target.value })}
              />
            </Field>
          ) : null}
          <Field label="Surface attribute" htmlFor="agent-surface" info="Attribute that names the surface a turn came from, such as Slack or Telegram.">
            <Input id="agent-surface" className="font-mono" data-testid="agent-setting-surface-from" placeholder="apgar.surface" value={draft.surface_from} onChange={(event) => set({ surface_from: event.target.value })} />
          </Field>
          <Field label="Output format" htmlFor="agent-format" info="json enables the format failure metric.">
            <Select id="agent-format" data-testid="agent-setting-output-format" value={draft.output_format} onChange={(event) => set({ output_format: event.target.value as "text" | "json" })}>
              <option value="text">text</option>
              <option value="json">json</option>
            </Select>
          </Field>
        </fieldset>
        <fieldset className="m-0 grid gap-4 border-0 p-0 sm:grid-cols-2">
          <legend className="mb-3 p-0 text-xs font-semibold text-muted-foreground">Integrations</legend>
          <Field
            label="Slack connection"
            htmlFor="agent-slack"
            info="Posts release verdicts to this channel."
            hint={
              slack.length === 0 ? (
                <span className="text-xs text-muted-foreground">
                  No Slack connection yet. <Link to="/settings" search={{ tab: "connections" }}>Add one in Connections</Link>
                </span>
              ) : null
            }
          >
            <Select id="agent-slack" data-testid="agent-setting-slack" disabled={slack.length === 0 && !draft.slack_connection} value={draft.slack_connection} onChange={(event) => set({ slack_connection: event.target.value })}>
              <option value="">No Slack connection</option>
              {slack.map((item) => (
                <option key={item.id} value={item.id}>{item.name}</option>
              ))}
            </Select>
          </Field>
        </fieldset>
      </PanelBody>
    </SectionForm>
  );
}

function readSource(agent: AgentOut): { connection: string; conditions: Condition[] } {
  return { connection: agent.langfuse_connection ?? "", conditions: fromFilter(agent.filter) };
}

function SourceSection({ agent, onDirty }: { agent: AgentOut; onDirty: (dirty: boolean) => void }) {
  const connections = useConnections();
  const langfuse = (connections.data?.items ?? []).filter((item) => item.type === "langfuse");
  const state = useSection(agent, readSource, onDirty, (value) => ({
    connection: value.connection,
    filter: toFilter(value.conditions),
  }));
  const { draft } = state;
  const invalid = draft.connection === "" || draft.conditions.some((item) => conditionError(item, draft.conditions) !== "");
  return (
    <SectionForm
      title="Trace selection"
      description="Which Langfuse traces belong to this agent."
      dirty={state.dirty}
      saving={state.saving}
      saved={state.saved}
      invalid={invalid}
      onDiscard={state.discard}
      onSave={() =>
        void state.save({
          langfuse_connection: draft.connection,
          filter: { ...toFilter(draft.conditions), environment: agent.filter?.environment ?? null },
        })
      }
    >
      <PanelBody className="flex flex-col gap-4">
        <Field label="Connection" htmlFor="agent-langfuse-connection" required>
          <Select
            id="agent-langfuse-connection"
            data-testid="agent-setting-langfuse-connection"
            aria-required="true"
            value={draft.connection}
            onChange={(event) => state.setDraft({ ...draft, connection: event.target.value })}
          >
            <option value="" disabled>Select a connection</option>
            {langfuse.map((item) => (
              <option key={item.id} value={item.id}>{item.name}</option>
            ))}
          </Select>
        </Field>
        <TraceConditions
          conditions={draft.conditions}
          onChange={(conditions) => state.setDraft({ ...draft, conditions })}
        />
      </PanelBody>
    </SectionForm>
  );
}

function readMetrics(agent: AgentOut): Record<string, MetricSettings> {
  return structuredClone(agent.effective_metrics);
}

function MetricsSection({ agent, onDirty }: { agent: AgentOut; onDirty: (dirty: boolean) => void }) {
  const state = useSection(agent, readMetrics, onDirty);
  const { draft } = state;
  const update = (id: string, patch: Partial<MetricSettings>) => state.setDraft({ ...draft, [id]: { ...draft[id], ...patch } });
  const invalid = Object.values(draft).some((metric) => !(metric.tolerance > 0));
  return (
    <SectionForm
      title="Metrics"
      description="Guardrail metrics decide the verdict. Informational metrics are reported only."
      dirty={state.dirty}
      saving={state.saving}
      saved={state.saved}
      invalid={invalid}
      onDiscard={state.discard}
      onSave={() => {
        const metrics: Record<string, Partial<MetricSettings>> = {};
        for (const [id, metric] of Object.entries(draft)) {
          metrics[id] = {
            enabled: metric.enabled,
            tolerance: metric.tolerance,
            role: metric.role,
            direction: metric.direction,
            tolerance_mode: metric.tolerance_mode,
          };
        }
        void state.save({ metrics });
      }}
    >
      <PanelBody className="border-b border-border">
        <MetricCoverage coverage={agent.coverage} />
      </PanelBody>
      <div className="overflow-x-auto">
        <table className="w-full border-collapse text-sm">
          <thead className="border-b border-border text-left text-xs text-muted-foreground">
            <tr>
              <th className="px-4 py-2 font-medium">Metric</th>
              <th className="px-4 py-2 font-medium">Enabled</th>
              <th className="px-4 py-2 font-medium">Tolerance</th>
              <th className="px-4 py-2 font-medium">Role</th>
            </tr>
          </thead>
          {METRIC_GROUPS.map((group) => {
            const ids = group.ids.filter((id) => draft[id]);
            if (ids.length === 0) {
              return null;
            }
            return (
              <TableGroup key={group.title} title={group.title} colSpan={4} testId={`metric-group-${group.title}`}>
                {ids.map((id) => {
                  const metric = draft[id];
                  const shown = metric.tolerance * 100;
                  const blocked = id === "format_failure_rate" && agent.output_format !== "json";
                  const on = metric.enabled && !blocked;
                  return (
                    <tr key={id} className={cn("border-t border-border", !on && "text-muted-foreground")}>
                      <td className="px-4 py-2">
                        <div className="flex items-center gap-1.5 font-medium">
                          {metricLabel(id)}
                          <InfoTip label={metricLabel(id)}>
                            {metricDescription(id)}
                            <div className="mono mt-1 opacity-70">{id}</div>
                          </InfoTip>
                        </div>
                        {blocked ? (
                          <div className="text-xs" data-testid={`metric-blocked-${id}`}>
                            Needs output format json, set in General.
                          </div>
                        ) : null}
                      </td>
                      <td className="px-4 py-2">
                        <Switch
                          testId={`metric-enabled-${id}`}
                          label={`Enable ${id}`}
                          checked={on}
                          disabled={blocked}
                          onCheckedChange={(enabled) => update(id, { enabled })}
                        />
                      </td>
                      <td className="px-4 py-2">
                        <Suffixed suffix={metric.tolerance_mode === "abs" ? "pp" : "%"}>
                          <Input
                            aria-label={`${id} tolerance`}
                            data-testid={`metric-tolerance-${id}`}
                            className="num w-20 text-right"
                            type="number"
                            step="0.1"
                            min="0"
                            disabled={!on}
                            value={Number.isInteger(shown) ? shown : Number(shown.toFixed(2))}
                            onChange={(event) => {
                              if (event.target.value === "") {
                                return;
                              }
                              update(id, { tolerance: Number(event.target.value) / 100 });
                            }}
                          />
                        </Suffixed>
                      </td>
                      <td className="px-4 py-2">
                        <Select
                          aria-label={`${id} role`}
                          data-testid={`metric-role-${id}`}
                          disabled={!on}
                          value={metric.role}
                          onChange={(event) => update(id, { role: event.target.value as MetricSettings["role"] })}
                        >
                          <option value="guardrail">guardrail</option>
                          <option value="informational">informational</option>
                        </Select>
                      </td>
                    </tr>
                  );
                })}
              </TableGroup>
            );
          })}
        </table>
      </div>
    </SectionForm>
  );
}

function readVerdict(agent: AgentOut): VerdictSettings {
  return { ...agent.effective_verdict };
}

function VerdictSection({ agent, onDirty }: { agent: AgentOut; onDirty: (dirty: boolean) => void }) {
  const state = useSection(agent, readVerdict, onDirty);
  const { draft } = state;
  const errors = Object.fromEntries(
    VERDICT_GROUPS.flatMap((group) => group.fields).map((field) => [field, verdictError(field, draft[field])]),
  );
  const invalid = Object.values(errors).some(Boolean);
  return (
    <SectionForm
      title="Verdict rules"
      description="Sample sizes and confirmations behind PASS and FAIL."
      dirty={state.dirty}
      saving={state.saving}
      saved={state.saved}
      invalid={invalid}
      onDiscard={state.discard}
      onSave={() =>
        void state.save({
          verdict: {
            min_turns: draft.min_turns,
            min_sessions: draft.min_sessions,
            min_turns_slice: draft.min_turns_slice,
            fail_confirmations: draft.fail_confirmations,
            pass_confirmations: draft.pass_confirmations,
            max_window_hours: draft.max_window_hours,
            notify_healthy: draft.notify_healthy,
            include_mixed_sessions: draft.include_mixed_sessions,
            alpha: draft.alpha,
          },
        })
      }
    >
      <PanelBody className="flex flex-col gap-6">
        {VERDICT_GROUPS.map((group) => (
          <fieldset key={group.title} className="m-0 grid grid-cols-[repeat(auto-fill,minmax(min(100%,13rem),1fr))] gap-4 border-0 p-0">
            <legend className="mb-3 p-0 text-xs font-semibold text-muted-foreground">{group.title}</legend>
            {group.fields.map((field) => {
              const value = draft[field];
              if (typeof value === "boolean") {
                return (
                  <Field key={field} label={VERDICT_LABELS[field]} info={VERDICT_INFO[field]}>
                    <span className="flex h-8 items-center gap-2 text-sm">
                      <Switch testId={`verdict-setting-${field}`} label={VERDICT_LABELS[field]} checked={value} onCheckedChange={(next) => state.setDraft({ ...draft, [field]: next })} />
                      {value ? "On" : "Off"}
                    </span>
                  </Field>
                );
              }
              const error = errors[field];
              const input = (
                <Input
                  id={`verdict-${field}`}
                  data-testid={`verdict-setting-${field}`}
                  className="num"
                  type="number"
                  step="any"
                  aria-invalid={error ? true : undefined}
                  value={Number.isNaN(value) ? "" : String(value)}
                  onChange={(event) => state.setDraft({ ...draft, [field]: event.target.value === "" ? Number.NaN : Number(event.target.value) })}
                />
              );
              return (
                <Field
                  key={field}
                  label={VERDICT_LABELS[field]}
                  htmlFor={`verdict-${field}`}
                  info={VERDICT_INFO[field]}
                  hint={error ? <FieldError>{error}</FieldError> : null}
                >
                  {VERDICT_SUFFIX[field] ? <Suffixed suffix={VERDICT_SUFFIX[field]}>{input}</Suffixed> : input}
                </Field>
              );
            })}
          </fieldset>
        ))}
        {draft.alpha !== DEFAULT_ALPHA ? (
          <p data-testid="verdict-alpha-note" className="m-0 text-xs text-muted-foreground">
            Alpha is set to <span className="num">{draft.alpha}</span> in configuration. The default is {DEFAULT_ALPHA}.
          </p>
        ) : null}
      </PanelBody>
    </SectionForm>
  );
}

function DangerSection({ agent, onDeleted }: { agent: AgentOut; onDeleted: () => void }) {
  const queryClient = useQueryClient();
  const { confirm, dialog } = useConfirm();
  return (
    <Panel className="border-fail/40">
      <PanelHeader title="Danger zone" description="Actions here cannot be undone." />
      <div className="flex flex-wrap items-center justify-between gap-3 px-4 py-4">
        <div>
          <h4 className="m-0 text-sm font-semibold">Delete agent</h4>
          <p className="m-0 mt-0.5 text-xs text-muted-foreground">
            Removes {agent.name} and its settings. Traces that arrive later can create it again.
          </p>
        </div>
        <Button
          type="button"
          variant="danger"
          data-testid="agent-settings-delete"
          onClick={() => {
            const target = agent.name;
            void confirm({
              title: `Delete ${target}?`,
              description: (
                <>
                  <Mono>{target}</Mono> and its settings are removed. Traces that arrive later can create the agent again.
                </>
              ),
              confirmLabel: "Delete agent",
            })
              .then((ok) => {
                if (!ok) {
                  return;
                }
                return apiFetch(`/api/v1/agents/${encodeURIComponent(target)}`, { method: "DELETE" }).then(async () => {
                  toast(`Deleted ${target}`);
                  await queryClient.invalidateQueries({ queryKey: ["agents"] });
                  onDeleted();
                });
              })
              .catch((error: unknown) => failToast(error, "Delete failed"));
          }}
        >
          <Trash2 size={14} strokeWidth={2} aria-hidden="true" />
          Delete agent
        </Button>
      </div>
      {dialog}
    </Panel>
  );
}
