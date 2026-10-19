const PRODUCT_LABELS: Record<string, string> = {
  langfuse: "Langfuse",
  slack: "Slack",
  webhook: "Webhook",
  otlp: "OTLP",
};

export function productLabel(value: string): string {
  return PRODUCT_LABELS[value] ?? value;
}

const WARNING_LABELS: Record<string, string> = {
  untagged_share: "Untagged share above 5%",
  multiple_environments: "Multiple environments observed",
  behavior_coverage: "Behavior metrics mostly unavailable",
  sync_error: "Langfuse sync failing",
};

export function warningLabel(value: string): string {
  return WARNING_LABELS[value] ?? value.replaceAll("_", " ");
}
