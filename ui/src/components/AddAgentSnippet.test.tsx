import { render, screen } from "@testing-library/react";

import { AddAgentSnippet } from "@/components/AddAgentSnippet";

describe("AddAgentSnippet", () => {
  it("contains the token, agent, and environment", () => {
    render(
      <AddAgentSnippet token="apg_ing_testtokenvalue123456789012" agent="e2e-agent" environment="production" origin="http://localhost:8080" />,
    );
    const snippet = screen.getByTestId("add-agent-snippet");
    expect(snippet).toHaveTextContent("apg_ing_testtokenvalue123456789012");
    expect(snippet).toHaveTextContent("gen_ai.agent.name=e2e-agent");
    expect(snippet).toHaveTextContent("deployment.environment.name=production");
    expect(snippet).toHaveTextContent("/v1/traces");
  });
});
