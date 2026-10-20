import { useState } from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import {
  TraceConditions,
  conditionError,
  fromFilter,
  newCondition,
  toFilter,
  type Condition,
} from "@/components/TraceConditions";

function Harness({ initial }: { initial: Condition[] }) {
  const [conditions, setConditions] = useState(initial);
  return <TraceConditions conditions={conditions} onChange={setConditions} />;
}

describe("trace condition rules", () => {
  it("builds a filter and reads one back", () => {
    const conditions = fromFilter({
      trace_name: "support",
      tags: ["billing"],
      metadata: { team: "ops" },
    });
    expect(toFilter(conditions)).toEqual({
      trace_name: "support",
      tags: ["billing"],
      metadata: { team: "ops" },
      environment: null,
    });
    expect(fromFilter(null)).toHaveLength(1);
    const ready = { ...newCondition("tag"), value: "support" };
    expect(conditionError(ready, [ready])).toBe("");
  });

  it("rejects an empty value, a blank metadata key, and a duplicate", () => {
    const trace = { ...newCondition("trace_name"), id: 1, value: "" };
    const filled = { ...newCondition("trace_name"), id: 2, value: "support" };
    const again = { ...newCondition("trace_name"), id: 3, value: "support" };
    const meta = { ...newCondition("metadata"), id: 4, key: "", value: "" };
    const metaValue = { ...newCondition("metadata"), id: 5, key: "", value: "ops" };
    const metaKey = { ...newCondition("metadata"), id: 6, key: "team", value: "ops" };
    const metaAgain = { ...newCondition("metadata"), id: 7, key: "team", value: "other" };
    expect(conditionError(trace, [trace])).toBe("Set a value or remove this condition.");
    expect(conditionError(filled, [filled])).toBe("");
    expect(conditionError(again, [filled, again])).toBe("Duplicate condition.");
    expect(conditionError(meta, [meta])).toBe("Set a key and a value.");
    expect(conditionError(metaValue, [metaValue])).toBe("Set the metadata key.");
    expect(conditionError(metaAgain, [metaKey, metaAgain])).toBe("This key is already used.");
  });
});

describe("TraceConditions", () => {
  it("adds a condition, edits it, and removes it", async () => {
    const user = userEvent.setup();
    render(<Harness initial={fromFilter(null)} />);
    expect(screen.getByRole("button", { name: "Remove condition 1" })).toBeDisabled();
    await user.click(screen.getByTestId("add-agent-condition-add"));
    expect(screen.getByText("and")).toBeInTheDocument();
    await user.selectOptions(screen.getByTestId("add-agent-condition-kind-1"), "metadata");
    await user.type(screen.getByTestId("add-agent-condition-key-1"), "team");
    await user.type(screen.getByTestId("add-agent-condition-value-1"), "ops");
    await user.type(screen.getByTestId("add-agent-condition-value-0"), "support");
    expect(screen.queryByText("Set a value or remove this condition.")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Remove condition 2" }));
    expect(screen.queryByText("and")).not.toBeInTheDocument();
  });
});
