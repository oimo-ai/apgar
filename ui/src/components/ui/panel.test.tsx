import { render, screen } from "@testing-library/react";

import { Panel, PanelBody, PanelFooter, PanelHeader, TableEmpty } from "@/components/ui/panel";

describe("Panel", () => {
  it("renders a header, a body, a footer, and an empty row", () => {
    render(
      <Panel testId="panel" className="wide">
        <PanelHeader title="Agents" description="Two agents" actions={<button type="button">Add</button>} />
        <PanelBody className="tight">Body</PanelBody>
        <PanelFooter>Save</PanelFooter>
        <table>
          <tbody>
            <TableEmpty colSpan={2}>None</TableEmpty>
          </tbody>
        </table>
      </Panel>,
    );
    expect(screen.getByTestId("panel")).toHaveClass("wide");
    expect(screen.getByText("Two agents")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Add" })).toBeInTheDocument();
    expect(screen.getByText("Body")).toHaveClass("tight");
    expect(screen.getByText("Save")).toBeInTheDocument();
    expect(screen.getByText("None")).toBeInTheDocument();
  });

  it("renders a header without a description", () => {
    render(<PanelHeader title="Plain" />);
    expect(screen.getByRole("heading", { name: "Plain" })).toBeInTheDocument();
  });
});
