import { render, screen } from "@testing-library/react";

import { ConnectionIcon } from "@/components/ConnectionIcon";

describe("ConnectionIcon", () => {
  it("draws a known product and falls back to a webhook glyph", () => {
    const { rerender } = render(<ConnectionIcon type="slack" />);
    expect(screen.getByRole("img", { name: "Slack" }).querySelector("svg")).not.toBeNull();
    rerender(<ConnectionIcon type="langfuse" />);
    expect(screen.getByRole("img", { name: "Langfuse" })).toBeInTheDocument();
    rerender(<ConnectionIcon type="webhook" className="extra" />);
    const icon = screen.getByRole("img", { name: "Webhook" });
    expect(icon.querySelector("path[d^='M5.042']")).toBeNull();
    expect(icon).toHaveClass("extra");
  });
});
