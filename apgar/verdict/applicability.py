from __future__ import annotations

from dataclasses import dataclass

from apgar.domain.enums import MetricId, MetricUnit
from apgar.storage.types import ArmData, ArmToolCall, ArmTurn
from apgar.verdict.metrics import MetricSpec, unit_arrays

_TOOL_METRICS = {
    MetricId.tool_error_rate,
    MetricId.tool_retry_rate,
    MetricId.tool_calls_per_turn,
    MetricId.zero_tool_turn_rate,
}
_COVERAGE = 0.90
_TOKEN_COVERAGE = 0.95


@dataclass(frozen=True, slots=True)
class Applicability:
    applicable: bool
    na_reason: str | None
    unit: MetricUnit
    coverage: dict[str, float] | None


def _share(hits: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return hits / total


def _tool_total(turns: list[ArmTurn], tools: list[ArmToolCall]) -> int:
    return max(sum(turn.tool_calls for turn in turns), len(tools))


def _closed_sessions(turns: list[ArmTurn]) -> int:
    return len({turn.session_id for turn in turns if turn.session_closed})


def _na(unit: MetricUnit, reason: str, coverage: dict[str, float] | None = None) -> Applicability:
    return Applicability(False, reason, unit, coverage)


def _ok(unit: MetricUnit, coverage: dict[str, float] | None = None) -> Applicability:
    return Applicability(True, None, unit, coverage)


def _zero(
    spec: MetricSpec,
    cand_turns: list[ArmTurn],
    cand_tools: list[ArmToolCall],
    base_turns: list[ArmTurn],
    base_tools: list[ArmToolCall],
    unit: MetricUnit,
) -> bool:
    cand = ArmData(cand_turns, cand_tools, 0, 0, 0)
    base = ArmData(base_turns, base_tools, 0, 0, 0)
    left = unit_arrays(spec, cand, unit, turns=cand_turns, tools=cand_tools)
    right = unit_arrays(spec, base, unit, turns=base_turns, tools=base_tools)
    if spec.kind == "percentile":
        return left.values.size == 0 or right.values.size == 0
    return float(left.den.sum()) == 0 or float(right.den.sum()) == 0


def assess(
    spec: MetricSpec,
    cand_turns: list[ArmTurn],
    cand_tools: list[ArmToolCall],
    base_turns: list[ArmTurn],
    base_tools: list[ArmToolCall],
) -> Applicability:
    unit = spec.unit
    coverage: dict[str, float] | None = None
    if not spec.settings.enabled:
        return _na(unit, "disabled")
    metric = spec.id
    base_tool_total = _tool_total(base_turns, base_tools)
    if metric in _TOOL_METRICS and base_tool_total == 0:
        return _na(unit, "no_tools")
    if metric is MetricId.tool_retry_rate:
        cand = _share(sum(1 for tool in cand_tools if tool.has_args_hash), len(cand_tools))
        base = _share(sum(1 for tool in base_tools if tool.has_args_hash), len(base_tools))
        coverage = {"candidate": cand, "baseline": base}
        if cand < _COVERAGE or base < _COVERAGE:
            return _na(unit, "coverage", coverage)
    if metric is MetricId.loop_rate:
        cand = _share(sum(1 for turn in cand_turns if turn.loop_flag is not None), len(cand_turns))
        base = _share(sum(1 for turn in base_turns if turn.loop_flag is not None), len(base_turns))
        coverage = {"candidate": cand, "baseline": base}
        if cand < _COVERAGE or base < _COVERAGE:
            return _na(unit, "coverage", coverage)
    if metric is MetricId.format_failure_rate:
        cand = _share(sum(1 for turn in cand_turns if turn.format_ok is not None), len(cand_turns))
        base = _share(sum(1 for turn in base_turns if turn.format_ok is not None), len(base_turns))
        coverage = {"candidate": cand, "baseline": base}
        if cand == 0 or base == 0:
            return _na(unit, "no_content", coverage)
        if cand < _COVERAGE or base < _COVERAGE:
            return _na(unit, "coverage", coverage)
    if metric is MetricId.output_tokens_p50:
        cand_tokens = _share(
            sum(1 for turn in cand_turns if turn.output_tokens is not None), len(cand_turns)
        )
        base_tokens = _share(
            sum(1 for turn in base_turns if turn.output_tokens is not None), len(base_turns)
        )
        if cand_tokens >= _TOKEN_COVERAGE and base_tokens >= _TOKEN_COVERAGE:
            unit = MetricUnit.tokens
        else:
            cand_chars = _share(
                sum(1 for turn in cand_turns if turn.output_chars is not None), len(cand_turns)
            )
            base_chars = _share(
                sum(1 for turn in base_turns if turn.output_chars is not None), len(base_turns)
            )
            coverage = {"candidate": cand_chars, "baseline": base_chars}
            if cand_chars == 0 or base_chars == 0:
                return _na(MetricUnit.chars, "no_content", coverage)
            if cand_chars < _TOKEN_COVERAGE or base_chars < _TOKEN_COVERAGE:
                return _na(MetricUnit.chars, "coverage", coverage)
            unit = MetricUnit.chars
    if metric is MetricId.cost_per_turn:
        cand = _share(sum(1 for turn in cand_turns if turn.cost_usd is not None), len(cand_turns))
        base = _share(sum(1 for turn in base_turns if turn.cost_usd is not None), len(base_turns))
        coverage = {"candidate": cand, "baseline": base}
        if cand < _COVERAGE or base < _COVERAGE:
            return _na(unit, "no_cost", coverage)
    if metric is MetricId.turns_per_session:
        if _closed_sessions(cand_turns) < 10 or _closed_sessions(base_turns) < 10:
            return _na(unit, "no_sessions")
        cand_inferred = _share(
            sum(1 for turn in cand_turns if turn.session_inferred), len(cand_turns)
        )
        base_inferred = _share(
            sum(1 for turn in base_turns if turn.session_inferred), len(base_turns)
        )
        if cand_inferred > 0.5 or base_inferred > 0.5:
            return _na(unit, "no_sessions")
    if _zero(spec, cand_turns, cand_tools, base_turns, base_tools, unit):
        return _na(unit, "zero_denominator", coverage)
    return _ok(unit, coverage)
