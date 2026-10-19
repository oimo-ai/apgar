import { Check, Copy } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { copyText } from "@/lib/copy";

export function otlpSnippet(origin: string, token: string, agent: string, environment: string): string {
  const base = origin.replace(/\/$/, "");
  return [
    `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT=${base}/v1/traces`,
    "OTEL_EXPORTER_OTLP_TRACES_PROTOCOL=http/protobuf",
    `OTEL_EXPORTER_OTLP_TRACES_HEADERS=Authorization=Bearer ${token}`,
    `OTEL_RESOURCE_ATTRIBUTES=gen_ai.agent.name=${agent},deployment.environment.name=${environment}`,
  ].join("\n");
}

export function AddAgentSnippet({
  token,
  agent,
  environment,
  origin,
}: {
  token: string;
  agent: string;
  environment: string;
  origin: string;
}) {
  const [copied, setCopied] = useState(false);
  const text = otlpSnippet(origin, token, agent, environment);
  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs font-medium">Exporter environment</span>
        <Button
          type="button"
          variant="outline"
          size="sm"
          aria-label="Copy snippet"
          onClick={() => {
            void copyText(text).then(() => setCopied(true));
          }}
        >
          {copied ? <Check size={14} strokeWidth={2} aria-hidden="true" /> : <Copy size={14} strokeWidth={2} aria-hidden="true" />}
          {copied ? "Copied" : "Copy"}
        </Button>
      </div>
      <pre data-testid="add-agent-snippet" className="code-block m-0 overflow-x-auto p-3 whitespace-pre-wrap break-all">
        {text}
      </pre>
    </div>
  );
}
