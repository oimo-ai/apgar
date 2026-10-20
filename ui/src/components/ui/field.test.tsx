import { render, screen } from "@testing-library/react";

import { Field, FieldError, RequiredMark } from "@/components/ui/field";

describe("Field", () => {
  it("marks a required field and shows the hint", () => {
    render(
      <Field label="Host" htmlFor="host" required info="The Langfuse host." hint={<FieldError>Required</FieldError>}>
        <input id="host" />
      </Field>,
    );
    expect(screen.getByText("Host")).toBeInTheDocument();
    expect(screen.getByText("Required")).toBeInTheDocument();
    expect(document.querySelector("[aria-hidden='true']")).not.toBeNull();
  });

  it("renders the mark on its own", () => {
    const { container } = render(<RequiredMark />);
    expect(container.querySelector("[aria-hidden='true']")).not.toBeNull();
  });
});
