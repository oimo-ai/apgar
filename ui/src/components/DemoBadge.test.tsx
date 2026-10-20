import { render, screen } from "@testing-library/react";

import { DemoBadge } from "@/components/DemoBadge";

describe("DemoBadge", () => {
  it("marks demo data", () => {
    render(<DemoBadge />);
    expect(screen.getByTestId("demo-badge")).toHaveTextContent("demo data");
  });
});
