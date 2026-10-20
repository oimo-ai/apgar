import { render } from "@testing-library/react";

import { ApgarMark } from "@/components/ApgarMark";

describe("ApgarMark", () => {
  it("draws the mark", () => {
    const { container } = render(<ApgarMark />);
    expect(container.querySelector("svg")).not.toBeNull();
    expect(container.querySelectorAll("path")).toHaveLength(2);
  });
});
