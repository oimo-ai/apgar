import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useState } from "react";

import { useConfirm } from "@/components/ui/confirm";
import { Modal } from "@/components/ui/modal";

function Opener() {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button type="button" onClick={() => setOpen(true)}>
        Open
      </button>
      <Modal open={open} onOpenChange={setOpen} title="Details">
        <input aria-label="Field" />
      </Modal>
    </>
  );
}

function Confirmer() {
  const { confirm, dialog } = useConfirm();
  return (
    <>
      <button type="button" onClick={() => void confirm({ title: "Stop monitoring", confirmLabel: "Stop" })}>
        Ask
      </button>
      {dialog}
    </>
  );
}

describe("Modal", () => {
  it("returns focus to the element that opened it", async () => {
    render(<Opener />);
    const opener = screen.getByRole("button", { name: "Open" });
    opener.focus();
    fireEvent.click(opener);
    await screen.findByRole("dialog");
    fireEvent.keyDown(document.activeElement ?? document.body, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(opener).toHaveFocus();
  });

  it("focuses the confirm action first and still returns focus", async () => {
    render(<Confirmer />);
    const opener = screen.getByRole("button", { name: "Ask" });
    opener.focus();
    fireEvent.click(opener);
    await waitFor(() => expect(screen.getByTestId("confirm-accept")).toHaveFocus());
    fireEvent.click(screen.getByTestId("confirm-cancel"));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(opener).toHaveFocus();
  });
});
