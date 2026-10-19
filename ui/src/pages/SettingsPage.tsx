import { useNavigate, useSearch } from "@tanstack/react-router";
import { PlugZap, Plus, SlidersHorizontal, Trash2 } from "lucide-react";
import { type ReactNode, useEffect, useState } from "react";
import { toast } from "sonner";

import { ApiError, apiFetch } from "@/api/client";
import { useAgents, useConnections, useIngestTokens, useSettings } from "@/api/queries";
import type { ConnectionOut, RetentionSettings } from "@/api/types";
import { Mono } from "@/components/Mono";
import { NotificationsTab } from "@/components/NotificationsTab";
import { ErrorState, Loading } from "@/components/States";
import { AgentSettings } from "@/components/AgentSettings";
import { ConnectionIcon } from "@/components/ConnectionIcon";
import { Button } from "@/components/ui/button";
import { useConfirm } from "@/components/ui/confirm";
import { Field } from "@/components/ui/field";
import { Input, Select, Suffixed } from "@/components/ui/input";
import { Modal, ModalBody, ModalFooter } from "@/components/ui/modal";
import { Notice } from "@/components/ui/notice";
import { Panel, PanelBody, PanelFooter, PanelHeader, TableEmpty } from "@/components/ui/panel";
import { StatusPill } from "@/components/ui/status-pill";
import { TokenReveal } from "@/components/TokenReveal";
import { Switch } from "@/components/ui/switch";
import { formatRelative, formatUtc } from "@/lib/format";
import { productLabel } from "@/lib/labels";
import { RETENTION_FIELDS, RETENTION_MAX_DAYS, RETENTION_MIN_DAYS } from "@/lib/metrics";
import {
  CONNECTION_FIELDS,
  CONNECTION_TYPES,
  FETCH_CONTENT_DEFAULT,
  FETCH_CONTENT_INFO,
  FIELD_PREFIXES,
  newConnectionConfig,
} from "@/lib/connections";

const TABS = [
  ["connections", "Connections", "settings-tab-connections"],
  ["ingest-tokens", "Ingest tokens", "settings-tab-ingest-tokens"],
  ["agents", "Agents", "settings-tab-agents"],
  ["retention", "Retention", "settings-tab-retention"],
  ["appearance", "Appearance", "settings-tab-appearance"],
  ["telemetry", "Telemetry", "settings-tab-telemetry"],
  ["notifications", "Notifications", "settings-tab-notifications"],
] as const;

const SECRET_FIELDS = new Set(["secret_key", "secret"]);


const NAME_PLACEHOLDERS: Record<string, string> = {
  langfuse: "prod-langfuse",
  slack: "slack-releases",
  webhook: "deploy-webhook",
};

const FIELD_PLACEHOLDERS: Record<string, string> = {
  host: "https://cloud.langfuse.com",
  public_key: "pk-lf-…",
  secret_key: "sk-lf-…",
  webhook_url: "https://hooks.slack.com/services/…",
  url: "https://example.com/apgar/webhook",
  secret: "At least 16 characters",
};

function withPrefix(field: string, value: string): string {
  const prefix = FIELD_PREFIXES[field];
  if (!prefix) {
    return value;
  }
  const rest = value.startsWith(prefix) ? value.slice(prefix.length) : value;
  return rest.startsWith(prefix) ? rest : value;
}

const FIELD_HINTS: Record<string, string> = {
  public_key: "From Langfuse project settings, API keys.",
  secret_key: "Paired with the public key. Stored encrypted.",
  host: "Langfuse base URL, for example https://cloud.langfuse.com.",
  webhook_url: "Incoming webhook URL from your Slack app. Paste the full URL or the part after services/.",
  secret: "16 to 256 characters. Receivers verify X-Apgar-Signature with it.",
};

function humanize(id: string): string {
  const text = id.replace(/_days$/, "").replace(/_/g, " ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}

function failToast(error: unknown, fallback = "Request failed"): void {
  toast.error(error instanceof ApiError ? error.message : fallback);
}

function When({ iso }: { iso: string | null | undefined }) {
  if (!iso) {
    return <span className="text-muted-foreground">Never</span>;
  }
  return (
    <span className="whitespace-nowrap" title={formatUtc(iso)}>
      {formatRelative(iso)}
    </span>
  );
}

export function SettingsPage() {
  const search = useSearch({ strict: false });
  const navigate = useNavigate();
  const requested = typeof search.tab === "string" ? search.tab : "";
  const tab = TABS.some(([id]) => id === requested) ? requested : "connections";
  const settings = useSettings();
  if (settings.isPending && !settings.data) {
    return <Loading />;
  }
  if (!settings.data) {
    return <ErrorState error={settings.error} retry={() => void settings.refetch()} />;
  }
  return (
    <div data-testid="page-settings" className="flex flex-col gap-4">
      <div className="page-head">
        <div>
          <h2 className="page-title">Settings</h2>
          <p className="page-sub">Connections, tokens, per agent verdict rules, and instance preferences.</p>
        </div>
      </div>
      <div role="tablist" aria-label="Settings sections" className="tabs">
        {TABS.map(([id, label, testId]) => (
          <button
            key={id}
            type="button"
            role="tab"
            aria-selected={tab === id}
            data-testid={testId}
            className="tab"
            onClick={() => void navigate({ to: "/settings", search: { tab: id } })}
          >
            {label}
          </button>
        ))}
      </div>
      <div role="tabpanel" className="flex flex-col gap-4">
        {tab === "connections" ? <ConnectionsTab /> : null}
        {tab === "ingest-tokens" ? <IngestTokensTab /> : null}
        {tab === "agents" ? (
          <AgentSettings
            agentName={typeof search.agent === "string" ? search.agent : undefined}
            section={typeof search.section === "string" ? search.section : undefined}
            onNavigate={(next) => void navigate({ to: "/settings", search: { tab: "agents", ...next }, replace: true })}
          />
        ) : null}
        {tab === "retention" ? <RetentionTab /> : null}
        {tab === "appearance" ? <AppearanceTab /> : null}
        {tab === "telemetry" ? <TelemetryTab /> : null}
        {tab === "notifications" ? <NotificationsTab /> : null}
      </div>
    </div>
  );
}

function fieldInputType(field: string): "password" | "url" | "text" {
  if (SECRET_FIELDS.has(field)) {
    return "password";
  }
  return ["host", "url", "webhook_url"].includes(field) ? "url" : "text";
}

function NameCell({ name, meta }: { name: string; meta?: ReactNode }) {
  return (
    <div className="cell-name">
      <span className="cell-name-primary" title={name}>{name}</span>
      {meta ? <span className="cell-name-secondary">{meta}</span> : null}
    </div>
  );
}

function ConfigureConnectionModal({
  connection,
  onClose,
  onSaved,
}: {
  connection: ConnectionOut | null;
  onClose: () => void;
  onSaved: () => Promise<unknown>;
}) {
  const [name, setName] = useState("");
  const [fields, setFields] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [replacing, setReplacing] = useState<Set<string>>(new Set());

  useEffect(() => {
    if (!connection) {
      return;
    }
    setName(connection.name);
    setReplacing(new Set());
    const initial: Record<string, string> = {};
    for (const field of CONNECTION_FIELDS[connection.type] ?? []) {
      if (SECRET_FIELDS.has(field)) {
        continue;
      }
      const value = connection.config[field];
      initial[field] = value === undefined || value === null ? "" : String(value);
    }
    setFields(initial);
  }, [connection]);

  if (!connection) {
    return null;
  }
  const projectId = connection.config.project_id;

  return (
    <Modal
      open
      onOpenChange={(next) => (next ? undefined : onClose())}
      title={`Configure ${connection.name}`}
      description="Stored secrets are kept unless you enter a new value."
      testId="connection-configure-modal"
    >
      <form
        className="flex min-h-0 flex-1 flex-col"
        onSubmit={(event) => {
          event.preventDefault();
          const config: Record<string, unknown> = {};
          for (const field of CONNECTION_FIELDS[connection.type] ?? []) {
            const value = fields[field] ?? "";
            if (field === "fetch_content") {
              config[field] = value === "true";
            } else if (!SECRET_FIELDS.has(field) || value) {
              config[field] = value;
            }
          }
          setSaving(true);
          void apiFetch(`/api/v1/connections/${connection.id}`, {
            method: "PATCH",
            body: JSON.stringify({ name, config }),
          })
            .then(async () => {
              toast(`Saved ${name}. Run Test to check it.`);
              onClose();
              await onSaved();
            })
            .catch((error: unknown) => failToast(error, "Save failed"))
            .finally(() => setSaving(false));
        }}
      >
        <ModalBody className="flex flex-col gap-4">
          <div className="grid grid-cols-2 gap-4 max-sm:grid-cols-1">
            <Field label="Name" htmlFor="connection-configure-name">
              <Input
                id="connection-configure-name"
                data-testid="connection-configure-name"
                required
                value={name}
                onChange={(event) => setName(event.target.value)}
              />
            </Field>
            <Field label="Type">
              <div className="flex h-8 items-center gap-2">
                <ConnectionIcon type={connection.type} />
                <span>{productLabel(connection.type)}</span>
              </div>
            </Field>
          </div>
          {(CONNECTION_FIELDS[connection.type] ?? []).map((field) => {
            if (field === "fetch_content") {
              return (
                <Field key={field} label="Fetch content" info={FETCH_CONTENT_INFO}>
                  <Select
                    data-testid={`connection-configure-${field}`}
                    value={fields[field] === "true" ? "true" : "false"}
                    onChange={(event) => setFields((current) => ({ ...current, [field]: event.target.value }))}
                  >
                    <option value="true">true</option>
                    <option value="false">false</option>
                  </Select>
                </Field>
              );
            }
            const stored = SECRET_FIELDS.has(field);
            const current = connection.config[field];
            return (
              <Field
                key={field}
                label={humanize(field)}
                htmlFor={`connection-configure-${field}`}
                info={FIELD_HINTS[field]}
              >
                {stored && !replacing.has(field) ? (
                  <div className="flex gap-2">
                    <Input
                      id={`connection-configure-${field}`}
                      data-testid={`connection-configure-${field}`}
                      className="font-mono text-muted-foreground"
                      readOnly
                      aria-readonly="true"
                      value={String(current ?? "••••")}
                    />
                    <Button
                      type="button"
                      variant="outline"
                      data-testid={`connection-configure-${field}-replace`}
                      onClick={() => setReplacing((items) => new Set(items).add(field))}
                    >
                      Replace
                    </Button>
                  </div>
                ) : (
                  <div className="flex gap-2">
                    <Input
                      id={`connection-configure-${field}`}
                      data-testid={`connection-configure-${field}`}
                      type={fieldInputType(field)}
                      className="font-mono"
                      autoComplete="off"
                      spellCheck={false}
                      autoFocus={stored}
                      minLength={field === "secret" ? 16 : undefined}
                      placeholder={stored ? "New value" : FIELD_PLACEHOLDERS[field]}
                      required
                      value={fields[field] ?? ""}
                      onChange={(event) => setFields((values) => ({ ...values, [field]: event.target.value }))}
                    />
                    {stored ? (
                      <Button
                        type="button"
                        variant="ghost"
                        onClick={() => {
                          setReplacing((items) => {
                            const next = new Set(items);
                            next.delete(field);
                            return next;
                          });
                          setFields((values) => ({ ...values, [field]: "" }));
                        }}
                      >
                        Cancel
                      </Button>
                    ) : null}
                  </div>
                )}
              </Field>
            );
          })}
          {connection.type === "langfuse" ? (
            <Field label="Project ID" info="Read only. Test discovers it from the keys.">
              <div className="flex h-8 items-center">
                {typeof projectId === "string" && projectId ? <Mono>{projectId}</Mono> : <span className="text-muted-foreground">Not discovered yet</span>}
              </div>
            </Field>
          ) : null}
          <Notice tone="info">Status stays as it is until you run Test again.</Notice>
        </ModalBody>
        <ModalFooter>
          <Button type="button" variant="outline" onClick={onClose}>Cancel</Button>
          <Button type="submit" data-testid="connection-configure-save" disabled={saving}>
            {saving ? "Saving" : "Save changes"}
          </Button>
        </ModalFooter>
      </form>
    </Modal>
  );
}

function ConnectionsTab() {
  const connections = useConnections();
  const { confirm, dialog } = useConfirm();
  const [open, setOpen] = useState(false);
  const [type, setType] = useState("webhook");
  const [name, setName] = useState("");
  const [fields, setFields] = useState<Record<string, string>>({});
  const [results, setResults] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [editing, setEditing] = useState<ConnectionOut | null>(null);
  const [testing, setTesting] = useState<string | null>(null);
  if (connections.isPending && !connections.data) {
    return <Loading />;
  }
  if (!connections.data) {
    return <ErrorState error={connections.error} retry={() => void connections.refetch()} />;
  }
  const rows = connections.data.items;

  function close(): void {
    setOpen(false);
    setName("");
    setFields({});
  }

  async function remove(row: ConnectionOut): Promise<void> {
    const ok = await confirm({
      title: `Delete ${row.name}?`,
      description: (
        <>
          The {productLabel(row.type)} connection <Mono>{row.name}</Mono> is removed permanently. Agents that still use it must be
          changed first.
        </>
      ),
      confirmLabel: "Delete connection",
    });
    if (!ok) {
      return;
    }
    try {
      await apiFetch(`/api/v1/connections/${row.id}`, { method: "DELETE" });
      toast(`Deleted ${row.name}`);
      await connections.refetch();
    } catch (error) {
      if (error instanceof ApiError && error.status === 409) {
        toast.error("Connection is used by an agent");
        return;
      }
      failToast(error, "Delete failed");
    }
  }

  return (
    <>
      <Panel>
        <PanelHeader
          title="Connections"
          description="Langfuse sources, and Slack or webhook destinations for notifications."
          actions={
            <Button type="button" data-testid="connection-add" onClick={() => setOpen(true)}>
              <Plus size={15} strokeWidth={2} aria-hidden="true" />
              Add connection
            </Button>
          }
        />
        <div className="overflow-x-auto">
          <table className="data-table">
            <thead>
              <tr>
                <th>Name</th>
                <th>Status</th>
                <th>Last checked</th>
                <th>Last error</th>
                <th>
                  <span className="sr-only">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.length === 0 ? <TableEmpty colSpan={5}>No connections yet.</TableEmpty> : null}
              {rows.map((row) => (
                <tr key={row.id} data-testid={`connection-row-${row.id}`}>
                  <td>
                    <div className="flex items-center gap-2.5">
                      <ConnectionIcon type={row.type} />
                      <NameCell name={row.name} />
                    </div>
                  </td>
                  <td>
                    <StatusPill status={row.status} />
                  </td>
                  <td>
                    <When iso={row.last_checked_at} />
                  </td>
                  <td className="max-w-80 truncate text-muted-foreground" title={row.last_error ?? undefined}>
                    {row.last_error ?? ""}
                  </td>
                  <td>
                    <div className="flex items-center justify-end gap-2">
                      {results[row.id] ? (
                        <StatusPill status={results[row.id] ?? ""} testId={`connection-test-result-${row.id}`} />
                      ) : (
                        <span data-testid={`connection-test-result-${row.id}`} />
                      )}
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        data-testid={`connection-test-${row.id}`}
                        title="Send a test request with this connection"
                        disabled={testing === row.id}
                        onClick={() => {
                          setTesting(row.id);
                          void apiFetch<{ status: string }>(`/api/v1/connections/${row.id}/test`, { method: "POST" })
                            .then((result) => {
                              setResults((current) => ({ ...current, [row.id]: result.status }));
                              void connections.refetch();
                            })
                            .catch(() => setResults((current) => ({ ...current, [row.id]: "error" })))
                            .finally(() => setTesting(null));
                        }}
                      >
                        <PlugZap size={13} strokeWidth={2} aria-hidden="true" />
                        {testing === row.id ? "Testing" : "Test"}
                      </Button>
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        className="w-7 px-0"
                        data-testid={`connection-configure-${row.id}`}
                        aria-label={`Configure ${row.name}`}
                        title="Configure"
                        onClick={() => setEditing(row)}
                      >
                        <SlidersHorizontal size={14} strokeWidth={2} aria-hidden="true" />
                      </Button>
                      <Button
                        type="button"
                        variant="danger"
                        size="sm"
                        className="w-7 px-0"
                        data-testid={`connection-delete-${row.id}`}
                        aria-label={`Delete ${row.name}`}
                        title="Delete"
                        onClick={() => void remove(row)}
                      >
                        <Trash2 size={14} strokeWidth={2} aria-hidden="true" />
                      </Button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>
      {dialog}
      <ConfigureConnectionModal connection={editing} onClose={() => setEditing(null)} onSaved={() => connections.refetch()} />
      <Modal
        open={open}
        onOpenChange={(next) => (next ? setOpen(true) : close())}
        title="Add connection"
        description="Secrets are stored on the server and are not shown again."
        testId="connection-modal"
      >
        <form
          className="flex min-h-0 flex-1 flex-col"
          onSubmit={(event) => {
            event.preventDefault();
            const config = newConnectionConfig(type, fields);
            setSaving(true);
            void apiFetch("/api/v1/connections", {
              method: "POST",
              body: JSON.stringify({ name, type, config }),
            })
              .then(() => {
                toast(`Connection ${name} added`);
                close();
                return connections.refetch();
              })
              .catch((error: unknown) => failToast(error, "Save failed"))
              .finally(() => setSaving(false));
          }}
        >
          <ModalBody className="grid grid-cols-2 gap-4 max-sm:grid-cols-1">
            <Field label="Type" htmlFor="connection-type">
              <Select id="connection-type" data-testid="connection-type" value={type} onChange={(event) => {
                setType(event.target.value);
                setFields({});
              }}>
                {CONNECTION_TYPES.map((item) => (
                  <option key={item} value={item}>{productLabel(item)}</option>
                ))}
              </Select>
            </Field>
            <Field label="Name" htmlFor="connection-name">
              <Input id="connection-name" data-testid="connection-name" placeholder={NAME_PLACEHOLDERS[type]} required value={name} onChange={(event) => setName(event.target.value)} />
            </Field>
            {(CONNECTION_FIELDS[type] ?? []).map((field) =>
              field === "fetch_content" ? (
                <Field key={field} label="Fetch content" info={FETCH_CONTENT_INFO} className="col-span-full">
                  <Select
                    data-testid={`connection-field-${field}`}
                    value={fields[field] ?? FETCH_CONTENT_DEFAULT}
                    onChange={(event) => setFields((current) => ({ ...current, [field]: event.target.value }))}
                  >
                    <option value="true">true</option>
                    <option value="false">false</option>
                  </Select>
                </Field>
              ) : (
                <Field key={field} label={humanize(field)} htmlFor={`connection-field-${field}`} info={FIELD_HINTS[field]} className="col-span-full">
                  <Input
                    id={`connection-field-${field}`}
                    data-testid={`connection-field-${field}`}
                    type={fieldInputType(field)}
                    className="font-mono"
                    autoComplete="off"
                    spellCheck={false}
                    required
                    minLength={field === "secret" ? 16 : undefined}
                    placeholder={FIELD_PLACEHOLDERS[field]}
                    value={fields[field] ?? FIELD_PREFIXES[field] ?? ""}
                    onChange={(event) => setFields((current) => ({ ...current, [field]: withPrefix(field, event.target.value) }))}
                  />
                </Field>
              ),
            )}
          </ModalBody>
          <ModalFooter>
            <Button type="button" variant="outline" onClick={close}>Cancel</Button>
            <Button type="submit" data-testid="connection-save" disabled={saving}>
              {saving ? "Saving" : "Add connection"}
            </Button>
          </ModalFooter>
        </form>
      </Modal>
    </>
  );
}

function TokenModal({
  open,
  onClose,
  title,
  description,
  token,
  usage,
  submitLabel,
  submitTestId,
  pending,
  onSubmit,
  children,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  description: string;
  token: string;
  usage: ReactNode;
  submitLabel: string;
  submitTestId: string;
  pending: boolean;
  onSubmit: () => void;
  children: ReactNode;
}) {
  return (
    <Modal
      open={open}
      onOpenChange={(next) => (next ? undefined : onClose())}
      title={token ? "Token created" : title}
      description={token ? "Copy it now and store it somewhere safe. It is not shown again." : description}
    >
      {token ? (
        <>
          <ModalBody className="flex flex-col gap-4">
            <TokenReveal token={token} />
            <div className="text-sm text-muted-foreground">{usage}</div>
          </ModalBody>
          <ModalFooter>
            <Button type="button" data-testid="token-done" onClick={onClose}>Done</Button>
          </ModalFooter>
        </>
      ) : (
        <form
          className="flex min-h-0 flex-1 flex-col"
          onSubmit={(event) => {
            event.preventDefault();
            onSubmit();
          }}
        >
          <ModalBody className="flex flex-col gap-4">{children}</ModalBody>
          <ModalFooter>
            <Button type="button" variant="outline" onClick={onClose}>Cancel</Button>
            <Button type="submit" data-testid={submitTestId} disabled={pending}>
              {pending ? "Creating" : submitLabel}
            </Button>
          </ModalFooter>
        </form>
      )}
    </Modal>
  );
}

function IngestTokensTab() {
  const tokens = useIngestTokens();
  const agents = useAgents();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [agent, setAgent] = useState("");
  const [auto, setAuto] = useState(true);
  const [plaintext, setPlaintext] = useState("");
  const [pending, setPending] = useState(false);
  if (tokens.isPending) {
    return <Loading />;
  }
  const rows = tokens.data?.items ?? [];

  function close(): void {
    setOpen(false);
    setPlaintext("");
    setName("");
    setAgent("");
    setAuto(true);
  }

  return (
    <>
      <Panel>
        <PanelHeader
          title="Ingest tokens"
          description="Exporters send traces to /v1/traces with one of these tokens."
          actions={
            <Button type="button" data-testid="ingest-token-add" onClick={() => setOpen(true)}>
              <Plus size={15} strokeWidth={2} aria-hidden="true" />
              Add ingest token
            </Button>
          }
        />
        <div className="overflow-x-auto">
          <table className="data-table">
            <thead>
              <tr>
                <th>Name</th>
                <th>Prefix</th>
                <th>Agent</th>
                <th>Created</th>
                <th>Status</th>
                <th>
                  <span className="sr-only">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.length === 0 ? <TableEmpty colSpan={6}>No ingest tokens yet.</TableEmpty> : null}
              {rows.map((row) => (
                <tr key={row.id} data-testid={`ingest-token-row-${row.id}`}>
                  <td>
                    <NameCell name={row.name} meta={row.auto_create_agents ? "Creates agents automatically" : "Known agents only"} />
                  </td>
                  <td>
                    <Mono>{row.token_prefix}</Mono>
                  </td>
                  <td>{row.agent ?? <span className="text-muted-foreground">any</span>}</td>
                  <td>
                    <When iso={row.created_at} />
                  </td>
                  <td>
                    <StatusPill status={row.revoked_at ? "revoked" : "active"} />
                  </td>
                  <td className="text-right">
                    <Button
                      type="button"
                      variant="danger"
                      size="sm"
                      data-testid={`ingest-token-revoke-${row.id}`}
                      disabled={Boolean(row.revoked_at)}
                      onClick={() => {
                        void apiFetch(`/api/v1/ingest-tokens/${row.id}`, { method: "DELETE" })
                          .then(() => tokens.refetch())
                          .catch((error: unknown) => failToast(error));
                      }}
                    >
                      Revoke
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>
      <TokenModal
        open={open}
        onClose={close}
        title="Add ingest token"
        description="Exporters authenticate to /v1/traces with this token."
        token={plaintext}
        usage={
          <>
            Send it as <Mono>Authorization: Bearer &lt;token&gt;</Mono> from your OpenTelemetry exporter or collector.
          </>
        }
        submitLabel="Create token"
        submitTestId="ingest-token-create"
        pending={pending}
        onSubmit={() => {
          setPending(true);
          void apiFetch<{ token: string }>("/api/v1/ingest-tokens", {
            method: "POST",
            body: JSON.stringify({ name, agent: agent || null, auto_create_agents: auto }),
          })
            .then((created) => {
              setPlaintext(created.token);
              return tokens.refetch();
            })
            .catch((error: unknown) => failToast(error))
            .finally(() => setPending(false));
        }}
      >
        <Field label="Name" htmlFor="ingest-token-name">
          <Input id="ingest-token-name" data-testid="ingest-token-name" placeholder="prod-collector" required value={name} onChange={(event) => setName(event.target.value)} />
        </Field>
        <Field label="Agent" htmlFor="ingest-token-agent" info="Bind the token to one agent, or accept traffic for any agent.">
          <Select id="ingest-token-agent" data-testid="ingest-token-agent" value={agent} onChange={(event) => setAgent(event.target.value)}>
            <option value="">Any agent</option>
            {(agents.data?.items ?? []).map((item) => (
              <option key={item.name} value={item.name}>{item.name}</option>
            ))}
          </Select>
        </Field>
        <div className="flex items-start justify-between gap-4 rounded-md border border-border px-3 py-2.5">
          <div>
            <p className="m-0 text-sm font-medium">Create agents automatically</p>
            <p className="m-0 mt-0.5 text-xs text-muted-foreground">
              When a trace names an agent that does not exist yet, create it. When off, those traces are dropped and counted.
            </p>
          </div>
          <Switch checked={auto} onCheckedChange={setAuto} label="Create agents automatically" />
        </div>
      </TokenModal>
    </>
  );
}

function RetentionTab() {
  const settings = useSettings();
  const [values, setValues] = useState<Partial<RetentionSettings>>({});
  useEffect(() => {
    if (settings.data) {
      setValues(settings.data.retention);
    }
  }, [settings.data]);
  return (
    <Panel>
      <form
        noValidate
        onSubmit={(event) => {
          event.preventDefault();
          void apiFetch("/api/v1/settings", { method: "PATCH", body: JSON.stringify({ retention: values }) })
            .then(() => {
              toast("Retention saved");
              return settings.refetch();
            })
            .catch((error: unknown) => failToast(error));
        }}
      >
        <PanelHeader title="Retention" description="How long trace data and verdict history are kept." />
        <PanelBody className="grid grid-cols-[repeat(auto-fill,minmax(min(100%,16rem),1fr))] gap-4">
          {RETENTION_FIELDS.map((field) => (
            <Field key={field.name} label={field.label} htmlFor={`retention-${field.name}`} info={field.info}>
              <Suffixed suffix="days">
                <Input
                  id={`retention-${field.name}`}
                  data-testid={`retention-${field.name}`}
                  className="num w-24 text-right"
                  type="number"
                  min={
                    field.name === "verdict_history_days"
                      ? (values.trace_data_days ?? RETENTION_MIN_DAYS)
                      : RETENTION_MIN_DAYS
                  }
                  max={RETENTION_MAX_DAYS}
                  value={values[field.name] ?? ""}
                  onChange={(event) => {
                    if (event.target.value === "") {
                      return;
                    }
                    setValues((current) => ({ ...current, [field.name]: Number(event.target.value) }));
                  }}
                />
              </Suffixed>
            </Field>
          ))}
        </PanelBody>
        <PanelFooter>
          <Button type="submit" data-testid="retention-save">Save</Button>
        </PanelFooter>
      </form>
    </Panel>
  );
}

function AppearanceTab() {
  const settings = useSettings();
  const [theme, setTheme] = useState(settings.data?.appearance.default_theme ?? "system");
  return (
    <Panel>
      <form
        onSubmit={(event) => {
          event.preventDefault();
          void apiFetch("/api/v1/settings", {
            method: "PATCH",
            body: JSON.stringify({ appearance: { default_theme: theme } }),
          }).then(() => {
            toast("Appearance saved");
            return settings.refetch();
          }).catch((error: unknown) => failToast(error));
        }}
      >
        <PanelHeader title="Appearance" description="The theme new browsers start with. Each person can still pick their own from the top bar." />
        <PanelBody>
          <Field label="Default theme" htmlFor="appearance-default-theme" className="max-w-[20rem]">
            <Select id="appearance-default-theme" data-testid="appearance-default-theme" value={theme} onChange={(event) => setTheme(event.target.value as "system" | "light" | "dark")}>
              <option value="system">system</option>
              <option value="light">light</option>
              <option value="dark">dark</option>
            </Select>
          </Field>
        </PanelBody>
        <PanelFooter>
          <Button type="submit">Save</Button>
        </PanelFooter>
      </form>
    </Panel>
  );
}

function TelemetryTab() {
  const settings = useSettings();
  const telemetry = settings.data?.telemetry;
  const enabled = telemetry?.enabled ?? true;
  const envDisabled = telemetry?.disabled_by_environment ?? false;
  return (
    <>
      <Panel>
        <div className="flex items-start justify-between gap-4 px-4 py-3.5">
          <div>
            <h3 className="m-0 text-sm font-semibold">Anonymous usage telemetry</h3>
            <p className="m-0 mt-0.5 text-xs text-muted-foreground">
              Sends one small daily report. No prompts, completions, names, or identifiers of your users.
            </p>
          </div>
          <span className="flex items-center gap-2 text-sm">
            {enabled ? "On" : "Off"}
            <Switch
              testId="telemetry-toggle"
              label="Telemetry"
              checked={enabled}
              disabled={envDisabled}
              onCheckedChange={(next) => {
                if (envDisabled) {
                  return;
                }
                void apiFetch("/api/v1/settings", {
                  method: "PATCH",
                  body: JSON.stringify({ telemetry: { enabled: next } }),
                }).then(() => settings.refetch()).catch((error: unknown) => failToast(error));
              }}
            />
          </span>
        </div>
      </Panel>
      {envDisabled ? (
        <Notice tone="warning" title="Telemetry is disabled by environment">
          <Mono>APGAR_TELEMETRY=0</Mono> is set on the server, so the toggle above has no effect.
        </Notice>
      ) : null}
      <Panel testId="telemetry-payload">
        <PanelHeader title="Payload preview" description="The exact report the next send would contain." />
        <PanelBody className="flex flex-col gap-3">
          <dl className="m-0 grid grid-cols-[8rem_1fr] gap-x-3 gap-y-1.5 text-sm">
            <dt className="text-muted-foreground">Endpoint</dt>
            <dd className="m-0 min-w-0 break-all">
              <Mono>{telemetry?.endpoint}</Mono>
            </dd>
            <dt className="text-muted-foreground">Last sent</dt>
            <dd className="m-0">
              <When iso={telemetry?.last_sent_date} />
            </dd>
          </dl>
          <pre className="code-block">{JSON.stringify(telemetry?.payload_preview ?? null, null, 2)}</pre>
          <Notice>
            Disable telemetry with <Mono>APGAR_TELEMETRY=0</Mono>. The environment variable wins over this toggle.
          </Notice>
        </PanelBody>
      </Panel>
    </>
  );
}
