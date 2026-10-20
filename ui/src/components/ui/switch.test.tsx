import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { Switch } from "@/components/ui/switch";

describe("Switch", () => {
  it("toggles and stays put while disabled", async () => {
    const user = userEvent.setup();
    const onCheckedChange = vi.fn();
    const { rerender } = render(<Switch checked={false} onCheckedChange={onCheckedChange} label="Fetch content" testId="fetch" />);
    await user.click(screen.getByTestId("fetch"));
    expect(onCheckedChange).toHaveBeenCalledWith(true);
    rerender(<Switch checked onCheckedChange={onCheckedChange} label="Fetch content" disabled />);
    expect(screen.getByRole("switch")).toBeDisabled();
  });
});
