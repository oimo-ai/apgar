import { Link } from "@tanstack/react-router";
import { type FormEvent, type ReactNode, useEffect, useState } from "react";
import { toast } from "sonner";

import { ApiError, apiFetch } from "@/api/client";
import { useAgent, useConnections, useStatus } from "@/api/queries";
import { AddAgentSnippet } from "@/components/AddAgentSnippet";
import { InstrumentationSteps } from "@/components/MetricCoverage";
import { Mono } from "@/components/Mono";
import { TokenReveal } from "@/components/TokenReveal";
import { type Condition, conditionError, newCondition, toFilter, TraceConditions } from "@/components/TraceConditions";
import { Button } from "@/components/ui/button";
import { Field, FieldError, RequiredMark } from "@/components/ui/field";
import { Input, Select } from "@/components/ui/input";
import { Modal, ModalBody, ModalFooter } from "@/components/ui/modal";
import { Notice } from "@/components/ui/notice";
import { StatusPill } from "@/components/ui/status-pill";
import { RELEASE_OPTIONS, releaseValue as resolveRelease } from "@/lib/releaseAttributes";
import { cn } from "@/lib/utils";

type Source = "otlp" | "langfuse";

const NAME_PATTERN = /^[a-z0-9][a-z0-9._-]{0,63}$/;

const SOURCES: { value: Source; title: string; description: string }[] = [
  { value: "otlp", title: "OTLP", description: "Send spans to Apgar with an ingest token." },
  { value: "langfuse", title: "Langfuse", description: "Pull traces from a Langfuse project." },
];

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <fieldset className="m-0 flex min-w-0 flex-col gap-4 border-0 p-0">
      <legend className="mb-3 p-0 text-sm font-semibold">{title}</legend>
      {children}
    </fieldset>
  );
}

export function AddAgentModal({
  open,
  onOpenChange,
  onCreated,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCreated: () => void;
}) {
  const connections = useConnections();
  const status = useStatus();
  const [name, setName] = useState("");
  const [source, setSource] = useState<Source>("otlp");
  const [environment, setEnvironment] = useState("production");
  const [connection, setConnection] = useState("");
  const [conditions, setConditions] = useState<Condition[]>(() => [newCondition()]);
  const [releaseFrom, setReleaseFrom] = useState("");
  const [customRelease, setCustomRelease] = useState("");
  const [slack, setSlack] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const [created, setCreated] = useState("");
  const [token, setToken] = useState("");

  const agent = useAgent(created);
  const refetchAgent = agent.refetch;
  useEffect(() => {
    if (!created) {
      return;
    }
    const timer = window.setInterval(() => void refetchAgent(), 5_000);
    return () => window.clearInterval(timer);
  }, [created, refetchAgent]);

  const items = connections.data?.items ?? [];
  const langfuse = items.filter((item) => item.type === "langfuse");
  const slackConnections = items.filter((item) => item.type === "slack");
  const ready = (agent.data?.activity.turns_24h ?? 0) > 0;

  const nameInvalid = name !== "" && !NAME_PATTERN.test(name);
  const conditionsValid = conditions.every((item) => conditionError(item, conditions) === "");
  const releaseValue = resolveRelease(releaseFrom, customRelease);
  const valid =
    NAME_PATTERN.test(name) &&
    releaseValue !== "" &&
    (source === "otlp" || (connection !== "" && conditionsValid));

  function reset() {
    setName("");
    setSource("otlp");
    setEnvironment("production");
    setConnection("");
    setConditions([newCondition()]);
    setReleaseFrom("");
    setCustomRelease("");
    setSlack("");
    setPending(false);
    setError("");
    setCreated("");
    setToken("");
  }

  function close() {
    onOpenChange(false);
    reset();
  }

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (!valid) {
      return;
    }
    setError("");
    setPending(true);
    try {
      await apiFetch(`/api/v1/agents`, {
        method: "POST",
        body: JSON.stringify({
          name,
          source,
          langfuse_connection: source === "langfuse" ? connection : null,
          filter: source === "langfuse" ? toFilter(conditions) : null,
          environment: environment.trim() || null,
          release: { from: releaseValue },
          output_format: "text",
          slack_connection: slack || null,
        }),
      });
      if (source === "otlp") {
        const createdToken = await apiFetch<{ token: string }>("/api/v1/ingest-tokens", {
          method: "POST",
          body: JSON.stringify({ name: `${name} (auto)`, agent: name, auto_create_agents: false }),
        });
        setToken(createdToken.token);
      }
      setCreated(name);
      toast(`Agent ${name} created`);
      onCreated();
    } catch (err) {
      const message = err instanceof ApiError ? err.message : "Could not create the agent";
      setError(message);
    } finally {
      setPending(false);
    }
  }

  return (
    <Modal
      open={open}
      onOpenChange={(next) => (next ? onOpenChange(true) : close())}
      size="lg"
      title={created ? "Agent created" : "Add agent"}
      description={
        created
          ? source === "otlp"
            ? "Copy the token now and configure your exporter. The token is not shown again."
            : "Apgar starts pulling matching traces from Langfuse."
          : "Choose where traces come from, then how Apgar finds releases in them."
      }
      testId="page-add-agent"
    >
      {created ? (
        <>
          <ModalBody className="flex flex-col gap-4">
            {token ? (
              <>
                <TokenReveal token={token} testId="add-agent-token" />
                <AddAgentSnippet
                  token={token}
                  agent={created}
                  environment={environment || "production"}
                  origin={status.data?.public_url || window.location.origin}
                />
              </>
            ) : (
              <Notice>
                The connector polls Langfuse every 60 seconds. Traces from about 30 minutes before now are included.
              </Notice>
            )}
            <div className="flex items-center gap-2 text-sm">
              <StatusPill status={ready ? "active" : "pending"} />
              {ready ? (
                <span data-testid="add-agent-first-turn">First turn received.</span>
              ) : (
                <span data-testid="add-agent-waiting" className="text-muted-foreground">
                  Waiting for the first turn…
                </span>
              )}
            </div>
            <InstrumentationSteps source={source} coverage={agent.data?.coverage ?? null} />
          </ModalBody>
          <ModalFooter>
            <Button type="button" variant="outline" asChild>
              <Link to="/agents/$agent" params={{ agent: created }}>Open agent</Link>
            </Button>
            <Button type="button" data-testid="add-agent-done" onClick={close}>Done</Button>
          </ModalFooter>
        </>
      ) : (
        <form className="flex min-h-0 flex-1 flex-col" noValidate onSubmit={(event) => void onSubmit(event)}>
          <ModalBody className="flex flex-col gap-6">
            <Section title="Agent">
              <div className="grid grid-cols-2 gap-4 max-sm:grid-cols-1">
                <Field
                  label="Name"
                  htmlFor="add-agent-name"
                  required
                  info="Apgar's identifier for this agent, used in URLs. Lowercase letters, digits, dot, dash, underscore. Cannot be changed later."
                  hint={nameInvalid ? <FieldError>Use lowercase letters, digits, dot, dash, or underscore.</FieldError> : null}
                >
                  <Input
                    id="add-agent-name"
                    data-testid="add-agent-name"
                    className="font-mono"
                    autoComplete="off"
                    spellCheck={false}
                    autoFocus
                    aria-required="true"
                    placeholder="support-agent"
                    aria-invalid={nameInvalid || undefined}
                    value={name}
                    onChange={(event) => setName(event.target.value)}
                  />
                </Field>
                <Field label="Environment" htmlFor="add-agent-environment" info="Only turns from this environment count toward verdicts. Empty accepts every environment.">
                  <Input
                    id="add-agent-environment"
                    data-testid="add-agent-environment"
                    className="font-mono"
                    autoComplete="off"
                    spellCheck={false}
                    placeholder="production"
                    value={environment}
                    onChange={(event) => setEnvironment(event.target.value)}
                  />
                </Field>
              </div>
              <div role="radiogroup" aria-label="Source" aria-required="true" className="flex flex-col gap-1.5">
                <span className="text-xs font-medium">Source<RequiredMark /></span>
                <div className="grid grid-cols-2 gap-3 max-sm:grid-cols-1">
                  {SOURCES.map((item) => {
                    const selected = source === item.value;
                    return (
                      <label
                        key={item.value}
                        className={cn(
                          "relative flex cursor-pointer flex-col gap-0.5 rounded-lg border px-3.5 py-3 has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-2 has-[:focus-visible]:outline-primary",
                          selected ? "border-primary bg-card" : "border-border bg-card hover:bg-muted",
                        )}
                      >
                        <input
                          type="radio"
                          name="add-agent-source"
                          className="absolute inset-0 m-0 cursor-pointer opacity-0"
                          data-testid={`add-agent-source-${item.value}`}
                          checked={selected}
                          onChange={() => setSource(item.value)}
                        />
                        <span className="inline-flex items-center gap-2 text-sm font-medium">
                          <span
                            aria-hidden="true"
                            className={cn(
                              "inline-block size-3.5 rounded-full border",
                              selected ? "border-4 border-primary" : "border-input",
                            )}
                          />
                          {item.title}
                        </span>
                        <span className="pl-5.5 text-xs text-muted-foreground">{item.description}</span>
                      </label>
                    );
                  })}
                </div>
              </div>
            </Section>

            {source === "langfuse" ? (
              <Section title="Trace selection">
                {langfuse.length === 0 && !connections.isPending ? (
                  <Notice tone="warning">
                    No Langfuse connection yet.{" "}
                    <Link to="/settings" search={{ tab: "connections" }}>Create a Langfuse connection</Link>{" "}
                    first.
                  </Notice>
                ) : (
                  <Field label="Connection" htmlFor="add-agent-connection" required>
                    <Select
                      id="add-agent-connection"
                      data-testid="add-agent-connection"
                      aria-required="true"
                      value={connection}
                      onChange={(event) => setConnection(event.target.value)}
                    >
                      <option value="">Select a connection</option>
                      {langfuse.map((item) => (
                        <option key={item.id} value={item.id}>{item.name}</option>
                      ))}
                    </Select>
                  </Field>
                )}
                <TraceConditions conditions={conditions} onChange={setConditions} />
              </Section>
            ) : null}

            <Section title="Release and integrations">
              <div className="grid grid-cols-2 gap-4 max-sm:grid-cols-1">
                <Field
                  label="Release attribute"
                  htmlFor="add-agent-release-from"
                  required
                  info="Span or resource attribute that carries the release identifier. Traces without it count as untagged."
                  className={releaseFrom === "custom" ? undefined : "col-span-full"}
                >
                  <Select
                    id="add-agent-release-from"
                    data-testid="add-agent-release-from"
                    aria-required="true"
                    className="w-full"
                    value={releaseFrom}
                    onChange={(event) => setReleaseFrom(event.target.value)}
                  >
                    <option value="" disabled>Select an attribute</option>
                    {RELEASE_OPTIONS.map(([value, label]) => (
                      <option key={value} value={value}>{label}</option>
                    ))}
                  </Select>
                </Field>
                {releaseFrom === "custom" ? (
                  <Field label="Custom attribute" htmlFor="add-agent-release-custom" required>
                    <Input
                      id="add-agent-release-custom"
                      data-testid="add-agent-release-custom"
                      aria-required="true"
                      className="font-mono"
                      autoComplete="off"
                      spellCheck={false}
                      placeholder="my.release.attribute"
                      value={customRelease}
                      onChange={(event) => setCustomRelease(event.target.value)}
                    />
                  </Field>
                ) : null}
                <Field
                  label="Slack connection"
                  htmlFor="add-agent-slack"
                  info="Posts release verdicts to this channel."
                  hint={
                    slackConnections.length === 0 ? (
                      <>
                        No Slack connection yet.{" "}
                        <Link to="/settings" search={{ tab: "connections" }}>Add one in Settings</Link>.
                      </>
                    ) : null
                  }
                >
                  <Select
                    id="add-agent-slack"
                    data-testid="add-agent-slack"
                    className="w-full"
                    disabled={slackConnections.length === 0}
                    value={slack}
                    onChange={(event) => setSlack(event.target.value)}
                  >
                    <option value="">None</option>
                    {slackConnections.map((item) => (
                      <option key={item.id} value={item.id}>{item.name}</option>
                    ))}
                  </Select>
                </Field>
              </div>
            </Section>

            {error ? <Notice tone="fail">{error}</Notice> : null}
          </ModalBody>
          <ModalFooter>
            {source === "otlp" ? (
              <span className="mr-auto text-xs text-muted-foreground">
                An ingest token for <Mono>{name || "this agent"}</Mono> is created with it.
              </span>
            ) : null}
            <Button type="button" variant="outline" onClick={close}>Cancel</Button>
            <Button type="submit" data-testid="add-agent-submit" disabled={!valid || pending}>
              {pending ? "Creating" : "Create agent"}
            </Button>
          </ModalFooter>
        </form>
      )}
    </Modal>
  );
}
