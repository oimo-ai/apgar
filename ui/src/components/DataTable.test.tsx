import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { DataTable } from "@/components/DataTable";

describe("DataTable", () => {
  it("opens the row from the row itself and leaves inner links alone", async () => {
    const user = userEvent.setup();
    const onOpen = vi.fn();
    render(
      <DataTable
        columns={[
          {
            id: "name",
            header: "Name",
            cell: () => <a href="https://example.com/docs">docs</a>,
          },
        ]}
        rows={[{ id: "a" }]}
        rowKey={(row) => row.id}
        onOpen={onOpen}
      />,
    );
    const link = screen.getByRole("link", { name: "docs" });
    await user.click(link);
    expect(onOpen).not.toHaveBeenCalled();
    link.focus();
    await user.keyboard("{Enter}");
    expect(onOpen).not.toHaveBeenCalled();
    const row = link.closest("tr");
    expect(row).not.toBeNull();
    row?.focus();
    await user.keyboard("{Enter}");
    expect(onOpen).toHaveBeenCalledTimes(1);
  });
});
