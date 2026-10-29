import { fireEvent, render, screen } from "@testing-library/react";

import { AgentsEmpty } from "@/components/AgentsEmpty";

describe("AgentsEmpty", () => {
  it("offers both paths, the next steps, and the privacy line", () => {
    const onAdd = vi.fn();
    const onSeed = vi.fn();
    render(<AgentsEmpty seeding={false} onAdd={onAdd} onSeed={onSeed} />);
    expect(screen.getByTestId("agents-empty")).toHaveTextContent("No agents yet");
    expect(screen.getByTestId("empty-setup-guide")).toHaveAttribute("href", "https://docs.useapgar.dev/quickstart");
    expect(screen.getByText("What happens next")).toBeInTheDocument();
    expect(screen.getAllByRole("listitem")).toHaveLength(3);
    expect(screen.getByTestId("empty-privacy")).toHaveTextContent("never stores prompts, completions, or tool arguments");
    fireEvent.click(screen.getByTestId("empty-add-agent"));
    fireEvent.click(screen.getByTestId("seed-demo-button"));
    expect(onAdd).toHaveBeenCalledOnce();
    expect(onSeed).toHaveBeenCalledOnce();
    expect(screen.queryByTestId("seed-demo-progress")).not.toBeInTheDocument();
  });

  it("disables the demo button while seeding", () => {
    render(<AgentsEmpty seeding onAdd={() => undefined} onSeed={() => undefined} />);
    expect(screen.getByTestId("seed-demo-button")).toBeDisabled();
    expect(screen.getByTestId("seed-demo-progress")).toHaveTextContent("Loading demo agents");
  });
});
