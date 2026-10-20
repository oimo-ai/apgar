import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { TableGroup } from "@/components/ui/table-group";

describe("TableGroup", () => {
  it("collapses its rows", async () => {
    const user = userEvent.setup();
    render(
      <table>
        <TableGroup title="Behavior" meta={<span>3</span>} colSpan={2} testId="group">
          <tr>
            <td>Retry rate</td>
          </tr>
        </TableGroup>
      </table>,
    );
    expect(screen.getByText("Retry rate")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /Behavior/ }));
    expect(screen.queryByText("Retry rate")).not.toBeInTheDocument();
    expect(screen.getByTestId("group")).toBeInTheDocument();
  });
});
