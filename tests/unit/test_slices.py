from __future__ import annotations

import numpy as np

from apgar.domain.enums import Direction, MetricId, MetricLevel, SliceDimension, SliceStatus
from apgar.domain.settings import VerdictSettings
from apgar.storage.types import ArmData
from apgar.verdict.metrics import default_specs, session_index
from apgar.verdict.slices import (
    SliceCell,
    apply_slice_results,
    benjamini_hochberg,
    dimension_values,
    ordered_cells,
    prepare_slices,
    slice_members,
    slice_p_value,
)
from tests.unit.test_metrics import NOW, arm, tool, turn


def test_bh_known_vector() -> None:
    adjusted = benjamini_hochberg([0.001, 0.01, 0.02, 0.04, 0.2])
    expected = [0.005, 0.025, 0.05 / 1.5, 0.05, 0.2]
    for got, want in zip(adjusted, expected, strict=True):
        assert abs(got - want) < 1e-12


def test_dimension_values() -> None:
    empty = arm([turn(0, surface="")], [])
    assert dimension_values(SliceDimension.surface, empty, empty, MetricLevel.turn) is None
    mixed = arm([turn(0, surface=""), turn(1, surface="web")], [])
    assert dimension_values(SliceDimension.surface, mixed, empty, MetricLevel.turn) == ["", "web"]
    inferred = arm([turn(0, session_inferred=True), turn(1, session_inferred=True)], [])
    assert (
        dimension_values(SliceDimension.session_depth, inferred, inferred, MetricLevel.turn) is None
    )
    named = arm([turn(0, tools_called=["sql_query"])], [tool(0, "sql_query")])
    other = arm([turn(1, tools_called=["send_email"])], [tool(1, "send_email")])
    assert dimension_values(SliceDimension.tool, named, other, MetricLevel.turn) == [
        "send_email",
        "sql_query",
    ]
    assert dimension_values(SliceDimension.session_depth, named, other, MetricLevel.session) is None


def test_tool_overlap_and_session_membership() -> None:
    turns = [
        turn(0, session_id="s", surface="web", tools_called=["sql_query"], start_ts=NOW),
        turn(1, session_id="s", surface="api", tools_called=[], start_ts=NOW),
    ]
    tools = [tool(0, "sql_query", surface="web")]
    data = arm(turns, tools)
    matched, _tool_rows, count = slice_members(
        data, SliceDimension.tool, "sql_query", MetricLevel.turn
    )
    assert [item.turn_id for item in matched] == ["t0"]
    assert count == 1
    session_turns, _tools, session_count = slice_members(
        data, SliceDimension.surface, "web", MetricLevel.session
    )
    assert session_count == 2
    assert {item.turn_id for item in session_turns} == {"t0", "t1"}


def test_slice_p_values() -> None:
    diffs = np.array([0.0, 0.01, 0.03, 0.04])
    assert slice_p_value(Direction.up, diffs, 0.02) == 0.5
    assert slice_p_value(Direction.down, diffs, 0.02) == 1.0
    both = slice_p_value(Direction.both, np.array([0.03, -0.03]), 0.02)
    assert both == 1.0


def test_insufficient_ordered_last() -> None:
    cells = [
        SliceCell(MetricId.tool_error_rate, "tool", "b", SliceStatus.INSUFFICIENT, 1, 1),
        SliceCell(MetricId.tool_error_rate, "tool", "a", SliceStatus.FAIL, 10, 10, delta=0.2),
        SliceCell(
            MetricId.tool_error_rate, "tool", "c", SliceStatus.NOT_FLAGGED, 10, 10, delta=0.01
        ),
    ]
    ordered = ordered_cells(cells, Direction.up)
    assert [cell.value for cell in ordered] == ["a", "c", "b"]


def test_few_turns_reason() -> None:
    specs = [spec for spec in default_specs() if spec.id is MetricId.tool_calls_per_turn]

    def side(count: int) -> ArmData:
        turns = [
            turn(i, tool_calls=1, zero_tool=False, tools_called=["search_kb"]) for i in range(count)
        ]
        return arm(turns, [tool(i, "search_kb") for i in range(count)])

    cand, base = side(3), side(5)
    families, _columns = prepare_slices(
        specs, cand, base, VerdictSettings(), session_index(cand), session_index(base)
    )
    cells = [cell for dimension in families["tool_calls_per_turn"].values() for cell in dimension]
    assert cells
    assert {cell.reason for cell in cells} == {"few_turns"}


def test_reason_after_resampling() -> None:
    metric = MetricId.tool_calls_per_turn
    specs = {spec.id.value: spec for spec in default_specs()}
    few = SliceCell(metric, "tool", "few", SliceStatus.INSUFFICIENT, 1, 1, reason="few_turns")
    missing = SliceCell(
        metric, "tool", "missing", SliceStatus.INSUFFICIENT, 200, 200, candidate=1.0, baseline=1.0
    )
    zero = SliceCell(
        metric, "tool", "zero", SliceStatus.INSUFFICIENT, 200, 200, candidate=1.0, baseline=0.0
    )
    families = {metric.value: {"tool": [few, missing, zero]}}
    apply_slice_results(families, specs, {(metric.value, "tool", "zero"): np.zeros(50)})
    assert few.reason == "few_turns"
    assert missing.reason == "unstable"
    assert zero.reason == "zero_baseline"
    assert {few.status, missing.status, zero.status} == {SliceStatus.INSUFFICIENT}
