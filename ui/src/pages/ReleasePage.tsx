import { Link, useParams } from "@tanstack/react-router";
import { CircleStop, Loader2, TriangleAlert } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

import { ApiError, apiFetch } from "@/api/client";
import { useAgent, useAgentReleases, useEvaluations, useEvents, useRelease } from "@/api/queries";
import type { ReleaseDetail } from "@/api/types";
import { MetricsTable } from "@/components/MetricsTable";
import { Mono } from "@/components/Mono";
import { ReleaseStatus } from "@/components/release/ReleaseStatus";
import { ReleaseStrip } from "@/components/release/ReleaseStrip";
import { SlicesSection } from "@/components/SlicesSection";
import { ErrorState, Loading } from "@/components/States";
import { Button } from "@/components/ui/button";
import { useConfirm } from "@/components/ui/confirm";
import { Select } from "@/components/ui/input";
import { Modal, ModalBody, ModalFooter } from "@/components/ui/modal";
import { Panel, PanelHeader } from "@/components/ui/panel";
import { ReasonTip } from "@/components/ui/tooltip";
import { METRIC_GROUPS, metricLabel } from "@/lib/metrics";
import { verdictSummary } from "@/lib/verdictSummary";

const QUEUE_TIMEOUT_MS = 90_000;

function AgentLine({ detail }: { detail: ReleaseDetail }) {
  return (
    <p className="page-sub">
      Agent{" "}
      <Link to="/agents/$agent" params={{ agent: detail.agent }}>
        {detail.agent}
      </Link>
    </p>
  );
}

function stopReason(detail: ReleaseDetail): string | null {
  if (detail.actions.stop.enabled) {
    return null;
  }
  return detail.final ? "Monitoring has already ended." : "Stop requested. The final check is queued.";
}

export function ReleasePage() {
  const params = useParams({ strict: false });
  const agent = typeof params.agent === "string" ? params.agent : "";
  const release = typeof params.release === "string" ? params.release : "";
  const [watch, setWatch] = useState<string | null>(null);
  const [stale, setStale] = useState(false);
  const detailQuery = useRelease(agent, release, watch !== null);
  const detail = detailQuery.data;
  const queued = watch !== null && (detail?.verdict_updated_at ?? "") === watch;
  const live = detail ? !detail.final : false;
  const evaluations = useEvaluations(agent, release, queued, live);
  const events = useEvents(agent, release, queued, live);
  const releases = useAgentReleases(agent);
  const agentQuery = useAgent(agent);
  const { confirm, dialog: confirmDialog } = useConfirm();
  const [metric, setMetric] = useState<string | null | undefined>(undefined);
  const [expectedOpen, setExpectedOpen] = useState(false);
  const [expected, setExpected] = useState<string[]>([]);
  const [pendingBaseline, setPendingBaseline] = useState<string | null>(null);

  const items = detail?.evaluation?.metrics.items;
  const selectedMetric = metric === undefined ? (detail?.summary?.failed_metrics[0]?.id ?? null) : metric;
  const history = useMemo(() => evaluations.data?.items ?? [], [evaluations.data]);

  useEffect(() => {
    if (watch === null) {
      return;
    }
    if ((detail?.verdict_updated_at ?? "") !== watch) {
      setWatch(null);
      setStale(false);
      setPendingBaseline(null);
      return;
    }
    const timer = window.setTimeout(() => {
      setWatch(null);
      setStale(true);
      setPendingBaseline(null);
    }, QUEUE_TIMEOUT_MS);
    return () => window.clearTimeout(timer);
  }, [detail?.verdict_updated_at, watch]);

  if (!detail) {
    if (detailQuery.isPending) {
      return <Loading />;
    }
    return <ErrorState error={detailQuery.error} retry={() => void detailQuery.refetch()} />;
  }

  const base = `/api/v1/agents/${encodeURIComponent(agent)}/releases/${encodeURIComponent(release)}`;
  const evaluation = detail.evaluation;
  const settings = agentQuery.data?.effective_verdict;
  const summary = verdictSummary(detail, settings, history);
  const isFail = detail.state === "FAIL";
  const currentBaseline = detail.baseline.release;
  const shownBaseline = pendingBaseline ?? currentBaseline ?? "";
  const manualBaseline = detail.user_state.manual_baseline !== null || detail.baseline.mode === "manual";
  const seenAt = Date.parse(detail.first_seen);
  const baselineOptions = (releases.data?.items ?? []).filter((row) => Date.parse(row.first_seen) < seenAt).map((row) => row.release);
  if (currentBaseline && !baselineOptions.includes(currentBaseline)) {
    baselineOptions.unshift(currentBaseline);
  }

  async function post(path: string, body: unknown): Promise<boolean> {
    try {
      await apiFetch(path, { method: "POST", body: JSON.stringify(body) });
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Request failed");
      return false;
    }
    setStale(false);
    setWatch(detail?.verdict_updated_at ?? "");
    toast("Evaluation queued");
    return true;
  }

  async function changeBaseline(next: string) {
    if (!next || next === currentBaseline) {
      return;
    }
    const ok = await confirm({
      title: "Change baseline",
      description: (
        <div className="flex flex-col gap-2">
          <p className="m-0">
            <Mono>{release}</Mono> will be compared with the traffic <Mono>{next}</Mono> served in the 7 days before <Mono>{release}</Mono>{" "}
            was first seen.
          </p>
          <p className="m-0 text-muted-foreground">The release is re-evaluated now and confirmation starts over.</p>
        </div>
      ),
      confirmLabel: "Change and re-evaluate",
      tone: "default",
    });
    if (!ok) {
      return;
    }
    setPendingBaseline(next);
    if (!(await post(`${base}/baseline`, { release: next }))) {
      setPendingBaseline(null);
    }
  }

  async function stopMonitoring() {
    const ok = await confirm({
      title: "Stop monitoring",
      description: (
        <div className="flex flex-col gap-2">
          <p className="m-0">Apgar runs a final check on the traffic collected so far and stops watching this release.</p>
          <p className="m-0 text-muted-foreground">
            That check decides the verdict, so the release can still end as a regression. This cannot be undone.
          </p>
        </div>
      ),
      confirmLabel: "Stop monitoring",
    });
    if (ok) {
      await post(`${base}/stop`, {});
    }
  }

  function selectMetric(id: string) {
    setMetric(selectedMetric === id ? null : id);
  }

  function metricDetail(id: string) {
    const item = items?.[id];
    if (!items || !item) {
      return null;
    }
    return (
      <div className="flex min-w-0 flex-col gap-2">
        <SlicesSection
          items={items}
          slices={evaluation?.slices}
          metric={id}
          minTurns={settings?.min_turns_slice}
        />
      </div>
    );
  }

  return (
    <div data-testid="page-release" className="flex flex-col gap-5">
      <header data-testid="release-header" className="flex flex-col gap-4">
        <div className="page-head">
          <div className="min-w-0">
            <h1 className="page-title mono" title={release}>
              {release}
            </h1>
            <AgentLine detail={detail} />
            <ReleaseStatus detail={detail} />
            {queued ? (
              <p data-testid="queued-indicator" role="status" className="m-0 mt-2 flex items-center gap-2 text-sm text-muted-foreground">
                <Loader2 size={14} className="animate-spin" aria-hidden="true" />
                Check running. The page updates when it finishes.
              </p>
            ) : null}
            {!queued && stale ? (
              <p role="status" className="m-0 mt-2 text-sm text-muted-foreground">
                The check is taking longer than expected.{" "}
                <button
                  type="button"
                  className="cursor-pointer text-primary underline"
                  onClick={() => {
                    setStale(false);
                    void detailQuery.refetch();
                    void evaluations.refetch();
                  }}
                >
                  Refresh
                </button>
              </p>
            ) : null}
          </div>

          <div className="flex shrink-0 flex-wrap items-end gap-2">
            <div data-testid="release-baseline" className="flex flex-col gap-1">
              <span className="flex items-center gap-1.5 text-[11px] tracking-wide text-muted-foreground uppercase">
                Baseline
                <span className="pill normal-case">{manualBaseline ? "manual" : "auto"}</span>
                {detail.baseline.unverified && currentBaseline ? (
                  <ReasonTip reason={`${currentBaseline} was not itself confirmed healthy.`}>
                    <TriangleAlert
                      size={13}
                      className="text-inconclusive"
                      aria-label={`${currentBaseline} was not itself confirmed healthy`}
                    />
                  </ReasonTip>
                ) : null}
              </span>
              <ReasonTip reason={detail.actions.baseline.enabled ? null : "Monitoring has ended, so the baseline can no longer change."}>
                <Select
                  aria-label="Baseline release"
                  data-testid="baseline-select"
                  className="min-w-44"
                  value={shownBaseline}
                  disabled={queued || baselineOptions.length === 0 || !detail.actions.baseline.enabled}
                  onChange={(event) => void changeBaseline(event.target.value)}
                >
                  {shownBaseline ? null : (
                    <option value="" disabled>
                      No baseline yet
                    </option>
                  )}
                  {baselineOptions.map((name) => (
                    <option key={name} value={name}>
                      {name}
                    </option>
                  ))}
                </Select>
              </ReasonTip>
            </div>
            <ReasonTip reason={stopReason(detail)}>
              <Button
                type="button"
                variant="outline"
                data-testid="action-stop"
                disabled={queued || !detail.actions.stop.enabled}
                onClick={() => void stopMonitoring()}
              >
                <CircleStop size={14} aria-hidden="true" />
                Stop monitoring
              </Button>
            </ReasonTip>
          </div>
        </div>

        <ReleaseStrip detail={detail} summary={summary} history={history} events={events.data?.items ?? []} settings={settings} />
      </header>

      <Panel testId="release-metrics">
        <PanelHeader
          title="Metrics"
          description="Select a metric to see where it changed."
          actions={
            <ReasonTip
              reason={
                detail.actions.expected_changes.enabled
                  ? null
                  : "Trace data for this release has expired, so it cannot be evaluated again."
              }
            >
              <Button
                type="button"
                variant="outline"
                size="sm"
                data-testid="action-expected"
                disabled={queued || !detail.actions.expected_changes.enabled}
                onClick={() => {
                  setExpected(detail.user_state.expected_changes);
                  setExpectedOpen(true);
                }}
              >
                Expected changes
                {detail.user_state.expected_changes.length > 0 ? (
                  <span className="num text-muted-foreground">{detail.user_state.expected_changes.length}</span>
                ) : null}
              </Button>
            </ReasonTip>
          }
        />
        <MetricsTable
          items={items}
          coverage={detail.coverage}
          selected={selectedMetric}
          onSelect={selectMetric}
          confirmed={isFail}
          collecting={summary.collecting}
          renderDetail={metricDetail}
        />
      </Panel>

      <Modal
        open={expectedOpen}
        onOpenChange={setExpectedOpen}
        title="Expected changes"
        description="Selected metrics are left out of the verdict and shown as expected. Saving re-evaluates the release and confirmation starts over."
      >
        <ModalBody className="flex flex-col gap-4">
          {METRIC_GROUPS.map((group) => (
            <fieldset key={group.title} className="m-0 flex flex-col gap-1.5 border-0 p-0">
              <legend className="mb-1 text-xs font-medium text-muted-foreground">{group.title}</legend>
              {group.ids.map((id) => (
                <label key={id} className="flex cursor-pointer items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    data-testid={`expected-metric-${id}`}
                    checked={expected.includes(id)}
                    onChange={(event) => {
                      setExpected((current) => (event.target.checked ? [...current, id] : current.filter((item) => item !== id)));
                    }}
                  />
                  {metricLabel(id)}
                  <span className="mono text-xs text-muted-foreground">{id}</span>
                </label>
              ))}
            </fieldset>
          ))}
        </ModalBody>
        <ModalFooter>
          <Button type="button" variant="outline" onClick={() => setExpectedOpen(false)}>
            Cancel
          </Button>
          <Button
            type="button"
            data-testid="dialog-confirm"
            disabled={
              expected.length === detail.user_state.expected_changes.length &&
              expected.every((id) => detail.user_state.expected_changes.includes(id))
            }
            onClick={() => {
              void post(`${base}/expected-changes`, { metrics: expected }).then((ok) => {
                if (ok) setExpectedOpen(false);
              });
            }}
          >
            Save and re-evaluate
          </Button>
        </ModalFooter>
      </Modal>

      {confirmDialog}
    </div>
  );
}
