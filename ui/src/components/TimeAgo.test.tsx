import { render, screen } from "@testing-library/react";

import { TimeAgo } from "@/components/TimeAgo";

describe("TimeAgo", () => {
  it("says n/a without a timestamp and titles a real one", () => {
    const { rerender } = render(<TimeAgo iso={null} />);
    expect(screen.getByText("n/a")).toBeInTheDocument();
    rerender(<TimeAgo iso="2026-10-08T09:30:00Z" />);
    expect(screen.getByTitle("2026-10-08 09:30 UTC").tagName).toBe("TIME");
  });
});
