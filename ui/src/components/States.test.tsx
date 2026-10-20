import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { ApiError } from "@/api/client";
import { EmptyState, ErrorState, Loading } from "@/components/States";

describe("States", () => {
  it("shows a loading and an empty state", () => {
    render(
      <>
        <Loading />
        <EmptyState>No agents yet</EmptyState>
      </>,
    );
    expect(screen.getByTestId("loading")).toHaveTextContent("Loading");
    expect(screen.getByTestId("empty-state")).toHaveTextContent("No agents yet");
  });

  it("shows the API message and retries", async () => {
    const user = userEvent.setup();
    const retry = vi.fn();
    const { rerender } = render(<ErrorState error={new ApiError(500, "error", "storage unavailable")} retry={retry} />);
    expect(screen.getByRole("alert")).toHaveTextContent("storage unavailable");
    await user.click(screen.getByRole("button", { name: "Retry" }));
    expect(retry).toHaveBeenCalledOnce();
    rerender(<ErrorState error={new Error("boom")} />);
    expect(screen.getByRole("alert")).toHaveTextContent("Something went wrong");
    expect(screen.queryByRole("button", { name: "Retry" })).not.toBeInTheDocument();
  });
});
