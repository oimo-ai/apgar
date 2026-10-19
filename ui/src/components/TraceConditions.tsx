import { Plus, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { RequiredMark } from "@/components/ui/field";
import { Input, Select } from "@/components/ui/input";
import { InfoTip } from "@/components/ui/tooltip";

export type ConditionKind = "trace_name" | "tag" | "metadata";

export type Condition = { id: number; kind: ConditionKind; key: string; value: string };

const KINDS: [ConditionKind, string][] = [
  ["trace_name", "Trace name"],
  ["tag", "Tag"],
  ["metadata", "Metadata"],
];

const PLACEHOLDERS: Record<ConditionKind, string> = {
  trace_name: "customer-support-agent",
  tag: "support",
  metadata: "support",
};

let nextId = 1;

export function newCondition(kind: ConditionKind = "trace_name"): Condition {
  return { id: nextId++, kind, key: "", value: "" };
}

export function conditionError(condition: Condition, all: Condition[]): string {
  if (condition.kind === "metadata" && condition.key.trim() === "") {
    return condition.value.trim() === "" ? "Set a key and a value." : "Set the metadata key.";
  }
  if (condition.value.trim() === "") {
    return "Set a value or remove this condition.";
  }
  const duplicate = all.find(
    (other) =>
      other.id < condition.id &&
      other.kind === condition.kind &&
      (condition.kind === "metadata"
        ? other.key.trim() === condition.key.trim()
        : other.value.trim() === condition.value.trim()),
  );
  if (duplicate) {
    return condition.kind === "metadata" ? "This key is already used." : "Duplicate condition.";
  }
  return "";
}

export function toFilter(conditions: Condition[]) {
  const metadata: Record<string, string> = {};
  const tags: string[] = [];
  let traceName: string | null = null;
  for (const condition of conditions) {
    const value = condition.value.trim();
    if (condition.kind === "trace_name") {
      traceName = value;
    } else if (condition.kind === "tag") {
      tags.push(value);
    } else {
      metadata[condition.key.trim()] = value;
    }
  }
  return { trace_name: traceName, tags, metadata, environment: null };
}

export function fromFilter(filter: { trace_name: string | null; tags: string[]; metadata: Record<string, string> } | null): Condition[] {
  const out: Condition[] = [];
  if (filter?.trace_name) {
    out.push({ ...newCondition("trace_name"), value: filter.trace_name });
  }
  for (const tag of filter?.tags ?? []) {
    out.push({ ...newCondition("tag"), value: tag });
  }
  for (const [key, value] of Object.entries(filter?.metadata ?? {})) {
    out.push({ ...newCondition("metadata"), key, value });
  }
  return out.length > 0 ? out : [newCondition()];
}

export function TraceConditions({
  conditions,
  onChange,
}: {
  conditions: Condition[];
  onChange: (next: Condition[]) => void;
}) {
  const traceNameUsed = (except: number) => conditions.some((item) => item.kind === "trace_name" && item.id !== except);

  function update(id: number, patch: Partial<Condition>) {
    onChange(conditions.map((item) => (item.id === id ? { ...item, ...patch } : item)));
  }

  return (
    <div className="flex flex-col gap-1.5">
      <span className="inline-flex items-center gap-1 text-xs font-medium">
        <span>
          Match traces where
          <RequiredMark />
        </span>
        <InfoTip label="Match traces where">
          Apgar imports only Langfuse traces that match every condition. This agent's releases, verdicts, and regressions are computed from them.
        </InfoTip>
      </span>
      <ol className="m-0 flex list-none flex-col gap-2 p-0" data-testid="add-agent-conditions">
        {conditions.map((condition, index) => {
          const error = conditionError(condition, conditions);
          const touched = condition.key !== "" || condition.value !== "";
          const showError = Boolean(error) && (touched || conditions.length > 1);
          return (
            <li key={condition.id} className="flex flex-col gap-1">
              {index > 0 ? (
                <span className="text-xs font-medium tracking-wide text-muted-foreground uppercase">and</span>
              ) : null}
              <div className="flex items-start gap-2">
                <Select
                  aria-label={`Condition ${index + 1} field`}
                  data-testid={`add-agent-condition-kind-${index}`}
                  value={condition.kind}
                  onChange={(event) => update(condition.id, { kind: event.target.value as ConditionKind, key: "" })}
                >
                  {KINDS.map(([kind, label]) => (
                    <option key={kind} value={kind} disabled={kind === "trace_name" && traceNameUsed(condition.id)}>
                      {label}
                    </option>
                  ))}
                </Select>
                {condition.kind === "metadata" ? (
                  <Input
                    aria-label={`Condition ${index + 1} metadata key`}
                    data-testid={`add-agent-condition-key-${index}`}
                    className="w-36 shrink-0 font-mono"
                    autoComplete="off"
                    spellCheck={false}
                    placeholder="agent"
                    aria-invalid={(showError && condition.key.trim() === "") || undefined}
                    value={condition.key}
                    onChange={(event) => update(condition.id, { key: event.target.value })}
                  />
                ) : null}
                <span className="inline-flex h-8 shrink-0 items-center text-xs text-muted-foreground">is</span>
                <Input
                  aria-label={`Condition ${index + 1} value`}
                  data-testid={`add-agent-condition-value-${index}`}
                  aria-required="true"
                  className="min-w-0 flex-1 font-mono"
                  autoComplete="off"
                  spellCheck={false}
                  placeholder={PLACEHOLDERS[condition.kind]}
                  aria-invalid={(showError && condition.value.trim() === "") || undefined}
                  value={condition.value}
                  onChange={(event) => update(condition.id, { value: event.target.value })}
                />
                <Button
                  type="button"
                  variant="ghost"
                  className="w-8 px-0"
                  aria-label={`Remove condition ${index + 1}`}
                  disabled={conditions.length === 1}
                  onClick={() => onChange(conditions.filter((item) => item.id !== condition.id))}
                >
                  <X size={14} strokeWidth={2} aria-hidden="true" />
                </Button>
              </div>
              {showError ? <p className="m-0 text-xs text-fail">{error}</p> : null}
            </li>
          );
        })}
      </ol>
      <div>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          className="-ml-2.5"
          data-testid="add-agent-condition-add"
          onClick={() => onChange([...conditions, newCondition(traceNameUsed(-1) ? "tag" : "trace_name")])}
        >
          <Plus size={14} strokeWidth={2} aria-hidden="true" />
          Add condition
        </Button>
      </div>
    </div>
  );
}
