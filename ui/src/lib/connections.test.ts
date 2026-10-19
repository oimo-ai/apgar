import { newConnectionConfig } from "@/lib/connections";

describe("newConnectionConfig", () => {
  it("fetches Langfuse content unless the user turns it off", () => {
    const fields = { host: "https://cloud.langfuse.com", public_key: "pk", secret_key: "sk" };
    expect(newConnectionConfig("langfuse", fields).fetch_content).toBe(true);
    expect(newConnectionConfig("langfuse", { ...fields, fetch_content: "false" }).fetch_content).toBe(false);
  });

  it("prefills the Slack webhook prefix", () => {
    expect(newConnectionConfig("slack", {})).toEqual({ webhook_url: "https://hooks.slack.com/services/" });
  });
});
