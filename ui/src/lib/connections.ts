export const CONNECTION_FIELDS: Record<string, string[]> = {
  langfuse: ["host", "public_key", "secret_key", "fetch_content"],
  slack: ["webhook_url"],
  webhook: ["url", "secret"],
};

export const FIELD_PREFIXES: Record<string, string> = {
  webhook_url: "https://hooks.slack.com/services/",
};

export const CONNECTION_TYPES = Object.keys(CONNECTION_FIELDS);

export const FETCH_CONTENT_DEFAULT = "true";

export const FETCH_CONTENT_INFO =
  "Pull message content and tool arguments from Langfuse. Retry rate, loop rate, format failure rate, and output length need it.";

export function newConnectionConfig(type: string, fields: Record<string, string>): Record<string, unknown> {
  const config: Record<string, unknown> = {};
  for (const field of CONNECTION_FIELDS[type] ?? []) {
    config[field] =
      field === "fetch_content"
        ? (fields[field] ?? FETCH_CONTENT_DEFAULT) === "true"
        : (fields[field] ?? FIELD_PREFIXES[field] ?? "");
  }
  return config;
}
