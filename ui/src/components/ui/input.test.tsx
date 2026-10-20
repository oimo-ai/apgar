import { render, screen } from "@testing-library/react";

import { Input, Select, Suffixed } from "@/components/ui/input";

describe("input", () => {
  it("renders an input, a select, and a suffix", () => {
    render(
      <>
        <Input aria-label="Host" className="extra" />
        <Select aria-label="Kind">
          <option value="tag">Tag</option>
        </Select>
        <Suffixed suffix="hours">
          <Input aria-label="Window" />
        </Suffixed>
      </>,
    );
    expect(screen.getByLabelText("Host")).toHaveClass("extra");
    expect(screen.getByLabelText("Kind")).toBeInTheDocument();
    expect(screen.getByText("hours")).toBeInTheDocument();
  });
});
