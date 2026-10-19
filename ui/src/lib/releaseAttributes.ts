export const RELEASE_OPTIONS = [
  ["apgar.release", "apgar.release"],
  ["gen_ai.agent.version", "gen_ai.agent.version"],
  ["langfuse.release", "langfuse.release"],
  ["service.version", "service.version"],
  ["custom", "Custom attribute…"],
] as const;

export function releaseChoice(from: string): { choice: string; custom: string } {
  if (from === "") {
    return { choice: "", custom: "" };
  }
  const known = RELEASE_OPTIONS.some(([value]) => value !== "custom" && value === from);
  return known ? { choice: from, custom: "" } : { choice: "custom", custom: from };
}

export function releaseValue(choice: string, custom: string): string {
  return choice === "custom" ? custom.trim() : choice;
}
