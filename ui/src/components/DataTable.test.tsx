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

  it("sorts from the header and opens a plain cell", async () => {
    const user = userEvent.setup();
    const onOpen = vi.fn();
    render(
      <DataTable
        caption="Agents"
        columns={[
          { id: "name", header: "Name", sortValue: (row: { name: string }) => row.name, cell: (row) => row.name },
          { id: "note", header: "Note", cell: () => "static" },
        ]}
        rows={[{ name: "zeta" }, { name: "alpha" }]}
        rowKey={(row) => row.name}
        onOpen={onOpen}
      />,
    );
    expect(screen.getByText("Agents")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Note" }));
    await user.click(screen.getByRole("button", { name: "Name" }));
    expect(screen.getAllByRole("row")[1]).toHaveTextContent("alpha");
    await user.click(screen.getByRole("button", { name: "Name" }));
    expect(screen.getAllByRole("row")[1]).toHaveTextContent("zeta");
    await user.click(screen.getByText("alpha"));
    expect(onOpen).toHaveBeenCalledWith({ name: "alpha" });
  });
});
