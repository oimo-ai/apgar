import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { TokenReveal } from "@/components/TokenReveal";

describe("TokenReveal", () => {
  it("shows the token and marks it copied", async () => {
    const user = userEvent.setup();
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText } });
    render(<TokenReveal token="apg_ing_once" />);
    expect(screen.getByTestId("token-plaintext")).toHaveTextContent("apg_ing_once");
    await user.click(screen.getByTestId("token-copy"));
    expect(writeText).toHaveBeenCalledWith("apg_ing_once");
    expect(screen.getByTestId("token-copy")).toHaveTextContent("Copied");
  });
});
