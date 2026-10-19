from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass

import numpy as np

from apgar.domain.enums import (
    Direction,
    MetricId,
    MetricLevel,
    SliceDimension,
    SliceStatus,
    ToleranceMode,
)
from apgar.domain.settings import VerdictSettings
from apgar.storage.types import ArmData, ArmToolCall, ArmTurn
from apgar.verdict.applicability import assess
from apgar.verdict.bootstrap import PercentileColumn, RatioColumn, interval
from apgar.verdict.metrics import MetricSpec, point_quantile, point_ratio, session_sums, unit_arrays
from apgar.verdict.power import delta_oriented

_DEPTHS = ("short", "medium", "long")


def _finite(value: float) -> float | None:
    if math.isnan(value) or math.isinf(value):
        return None
    return value


def benjamini_hochberg(p_values: list[float]) -> list[float]:
    count = len(p_values)
    if count == 0:
        return []
    order = sorted(range(count), key=lambda index: (p_values[index], index))
    adjusted = [1.0] * count
    running = 1.0
    for rank_from_end, index in enumerate(reversed(order)):
        rank = count - rank_from_end
        running = min(running, min(1.0, (count / rank) * p_values[index]))
        adjusted[index] = running
    return adjusted


def slice_p_value(direction: Direction, diffs: np.ndarray, tau: float) -> float:
    valid = diffs[np.isfinite(diffs)]
    if valid.size == 0:
        return 1.0
    if direction is Direction.both:
        left = float(np.mean(valid <= tau))
        right = float(np.mean(valid >= -tau))
        return min(1.0, 2 * min(left, right))
    oriented = valid if direction is not Direction.down else -valid
    return float(np.mean(oriented <= tau))


def _distinct(values: list[str]) -> list[str] | None:
    unique = sorted(set(values))
    if not unique or all(value == "" for value in unique):
        return None
    return unique


def dimension_values(
    dimension: SliceDimension, cand: ArmData, base: ArmData, level: MetricLevel
) -> list[str] | None:
    if level is MetricLevel.session and dimension is SliceDimension.session_depth:
        return None
    if dimension is SliceDimension.tool:
        names = sorted(
            {tool.tool_name for tool in cand.tool_calls}
            | {tool.tool_name for tool in base.tool_calls}
        )
        return names or None
    if dimension is SliceDimension.session_depth:
        arms = [arm for arm in (cand, base) if arm.turns]
        if not arms:
            return None
        if any(all(turn.session_inferred for turn in arm.turns) for arm in arms):
            return None
        return list(_DEPTHS)
    field = {
        SliceDimension.surface: "surface",
        SliceDimension.response_model: "response_model",
        SliceDimension.prompt_version: "prompt_version",
    }[dimension]
    values = [str(getattr(turn, field)) for turn in [*cand.turns, *base.turns]]
    return _distinct(values)


def _first_turns(turns: list[ArmTurn]) -> dict[str, ArmTurn]:
    chosen: dict[str, ArmTurn] = {}
    for turn in turns:
        current = chosen.get(turn.session_id)
        if current is None or (turn.start_ts, turn.turn_id) < (current.start_ts, current.turn_id):
            chosen[turn.session_id] = turn
    return chosen


def _turn_matches(turn: ArmTurn, dimension: SliceDimension, value: str) -> bool:
    if dimension is SliceDimension.tool:
        return value in turn.tools_called
    if dimension is SliceDimension.surface:
        return turn.surface == value
    if dimension is SliceDimension.response_model:
        return turn.response_model == value
    if dimension is SliceDimension.prompt_version:
        return turn.prompt_version == value
    if dimension is SliceDimension.session_depth:
        return (not turn.session_inferred) and turn.depth_bucket == value
    return False


def _tool_matches(
    tool: ArmToolCall, dimension: SliceDimension, value: str, turns: dict[str, ArmTurn]
) -> bool:
    if dimension is SliceDimension.tool:
        return tool.tool_name == value
    turn = turns.get(tool.turn_id)
    if turn is None:
        return False
    return _turn_matches(turn, dimension, value)


def slice_members(
    arm: ArmData, dimension: SliceDimension, value: str, level: MetricLevel
) -> tuple[list[ArmTurn], list[ArmToolCall], int]:
    by_turn = {turn.turn_id: turn for turn in arm.turns}
    if level is MetricLevel.session:
        first = _first_turns(arm.turns)
        if dimension is SliceDimension.tool:
            matched_sessions = {turn.session_id for turn in arm.turns if value in turn.tools_called}
        else:
            matched_sessions = {
                session_id
                for session_id, turn in first.items()
                if _turn_matches(turn, dimension, value)
            }
        turns = [turn for turn in arm.turns if turn.session_id in matched_sessions]
        tools = [tool for tool in arm.tool_calls if tool.session_id in matched_sessions]
        return turns, tools, len(turns)
    if level is MetricLevel.tool:
        tools = [tool for tool in arm.tool_calls if _tool_matches(tool, dimension, value, by_turn)]
        turn_ids = {tool.turn_id for tool in tools}
        turns = [turn for turn in arm.turns if turn.turn_id in turn_ids]
        return turns, tools, len(tools)
    turns = [turn for turn in arm.turns if _turn_matches(turn, dimension, value)]
    turn_ids = {turn.turn_id for turn in turns}
    tools = [tool for tool in arm.tool_calls if tool.turn_id in turn_ids]
    return turns, tools, len(turns)


@dataclass(slots=True)
class SliceCell:
    metric: MetricId
    dimension: str
    value: str
    status: SliceStatus
    n_candidate: int
    n_baseline: int
    candidate: float | None = None
    baseline: float | None = None
    delta: float | None = None
    ci: list[float] | None = None
    p_value: float | None = None
    p_adjusted: float | None = None
    reason: str | None = None


def _column(
    spec: MetricSpec,
    cand: ArmData,
    base: ArmData,
    cand_turns: list[ArmTurn],
    cand_tools: list[ArmToolCall],
    base_turns: list[ArmTurn],
    base_tools: list[ArmToolCall],
    unit: object,
    key: tuple[str, str, str],
    sessions_c: dict[str, int],
    sessions_b: dict[str, int],
    n_sessions_c: int,
    n_sessions_b: int,
) -> RatioColumn | PercentileColumn:
    from apgar.domain.enums import MetricUnit

    chosen = unit if isinstance(unit, MetricUnit) else spec.unit
    left = unit_arrays(spec, cand, chosen, turns=cand_turns, tools=cand_tools, sessions=sessions_c)
    right = unit_arrays(spec, base, chosen, turns=base_turns, tools=base_tools, sessions=sessions_b)
    rel = spec.settings.tolerance_mode is ToleranceMode.rel
    if spec.kind == "percentile":
        order_c = np.argsort(left.values, kind="mergesort")
        order_b = np.argsort(right.values, kind="mergesort")
        return PercentileColumn(
            key,
            spec.quantile or 0.5,
            left.values[order_c],
            left.session_idx[order_c],
            right.values[order_b],
            right.session_idx[order_b],
            rel,
        )
    num_c, den_c = session_sums(left, n_sessions_c)
    num_b, den_b = session_sums(right, n_sessions_b)
    return RatioColumn(key, num_c, den_c, num_b, den_b, rel)


def comparison_column(
    spec: MetricSpec,
    cand: ArmData,
    base: ArmData,
    cand_turns: list[ArmTurn],
    cand_tools: list[ArmToolCall],
    base_turns: list[ArmTurn],
    base_tools: list[ArmToolCall],
    unit: object,
    key: tuple[str, str, str],
    sessions_c: dict[str, int],
    sessions_b: dict[str, int],
    n_sessions_c: int,
    n_sessions_b: int,
) -> RatioColumn | PercentileColumn:
    return _column(
        spec,
        cand,
        base,
        cand_turns,
        cand_tools,
        base_turns,
        base_tools,
        unit,
        key,
        sessions_c,
        sessions_b,
        n_sessions_c,
        n_sessions_b,
    )


def prepare_slices(
    specs: list[MetricSpec],
    cand: ArmData,
    base: ArmData,
    vs: VerdictSettings,
    sessions_c: dict[str, int],
    sessions_b: dict[str, int],
) -> tuple[dict[str, dict[str, list[SliceCell]]], list[RatioColumn | PercentileColumn]]:
    families: dict[str, dict[str, list[SliceCell]]] = {spec.id.value: {} for spec in specs}
    columns: list[RatioColumn | PercentileColumn] = []
    n_c = len(sessions_c)
    n_b = len(sessions_b)
    for spec in specs:
        for dimension in SliceDimension:
            values = dimension_values(dimension, cand, base, spec.level)
            if values is None:
                families[spec.id.value][dimension.value] = []
                continue
            cells: list[SliceCell] = []
            for value in values:
                cand_turns, cand_tools, cand_n = slice_members(cand, dimension, value, spec.level)
                base_turns, base_tools, base_n = slice_members(base, dimension, value, spec.level)
                cell = SliceCell(
                    spec.id, dimension.value, value, SliceStatus.INSUFFICIENT, cand_n, base_n
                )
                if cand_n < vs.min_turns_slice or base_n < vs.min_turns_slice:
                    cell.reason = "few_turns"
                    cells.append(cell)
                    continue
                decision = assess(spec, cand_turns, cand_tools, base_turns, base_tools)
                if not decision.applicable:
                    cell.reason = decision.na_reason or "not_applicable"
                    cells.append(cell)
                    continue
                key = (spec.id.value, dimension.value, value)
                column = _column(
                    spec,
                    cand,
                    base,
                    cand_turns,
                    cand_tools,
                    base_turns,
                    base_tools,
                    decision.unit,
                    key,
                    sessions_c,
                    sessions_b,
                    n_c,
                    n_b,
                )
                if isinstance(column, RatioColumn):
                    cell.candidate = _finite(point_ratio(column.xc, column.dc))
                    cell.baseline = _finite(point_ratio(column.xb, column.db))
                else:
                    cell.candidate = _finite(point_quantile(column.vc, column.q))
                    cell.baseline = _finite(point_quantile(column.vb, column.q))
                columns.append(column)
                cells.append(cell)
            families[spec.id.value][dimension.value] = cells
    return families, columns


def apply_slice_results(
    families: dict[str, dict[str, list[SliceCell]]],
    specs: dict[str, MetricSpec],
    results: dict[tuple[str, str, str], np.ndarray],
) -> None:
    grouped: dict[tuple[str, str], list[SliceCell]] = defaultdict(list)
    for metric, dimensions in families.items():
        spec = specs[metric]
        for cells in dimensions.values():
            for cell in cells:
                if cell.status is SliceStatus.INSUFFICIENT and cell.candidate is None:
                    cell.reason = cell.reason or "unstable"
                    continue
                key = (metric, cell.dimension, cell.value)
                diffs = results.get(key)
                if diffs is None:
                    cell.status = SliceStatus.INSUFFICIENT
                    cell.reason = "unstable"
                    continue
                tau = spec.settings.tolerance
                if spec.settings.tolerance_mode is ToleranceMode.rel:
                    delta = None
                    if cell.candidate is not None and cell.baseline not in (None, 0):
                        delta = (cell.candidate - cell.baseline) / cell.baseline
                else:
                    delta = None
                    if cell.candidate is not None and cell.baseline is not None:
                        delta = cell.candidate - cell.baseline
                cell.delta = delta
                lower, upper, _se, share = interval(diffs, 0.05)
                if share < 0.5 or delta is None:
                    cell.status = SliceStatus.INSUFFICIENT
                    cell.reason = (
                        "zero_baseline" if delta is None and cell.baseline == 0 else "unstable"
                    )
                    cell.candidate = None
                    cell.baseline = None
                    cell.delta = None
                    continue
                cell.ci = [lower, upper]
                cell.p_value = slice_p_value(spec.settings.direction, diffs, tau)
                grouped[(metric, cell.dimension)].append(cell)
    for cells in grouped.values():
        adjusted = benjamini_hochberg(
            [1.0 if cell.p_value is None else cell.p_value for cell in cells]
        )
        for cell, p_adj in zip(cells, adjusted, strict=True):
            cell.p_adjusted = p_adj
            cell.status = SliceStatus.FAIL if p_adj <= 0.05 else SliceStatus.NOT_FLAGGED


def ordered_cells(cells: list[SliceCell], direction: Direction) -> list[SliceCell]:
    ready = [cell for cell in cells if cell.status is not SliceStatus.INSUFFICIENT]
    pending = [cell for cell in cells if cell.status is SliceStatus.INSUFFICIENT]
    ready.sort(
        key=lambda cell: delta_oriented(direction, cell.delta or 0.0),
        reverse=True,
    )
    pending.sort(key=lambda cell: cell.value)
    return [*ready, *pending]
