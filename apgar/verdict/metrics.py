from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np

from apgar.domain.enums import MetricId, MetricLevel, MetricUnit, OutputFormat
from apgar.domain.models import Agent
from apgar.domain.settings import (
    DEFAULT_METRICS,
    METRIC_LEVELS,
    MetricSettings,
    effective_metric_settings,
)
from apgar.storage.types import ArmData, ArmToolCall, ArmTurn


@dataclass(frozen=True, slots=True)
class MetricSpec:
    id: MetricId
    level: MetricLevel
    settings: MetricSettings
    unit: MetricUnit
    kind: Literal["ratio", "percentile"]
    quantile: float | None


@dataclass(slots=True)
class UnitArrays:
    num: np.ndarray
    den: np.ndarray
    values: np.ndarray
    session_idx: np.ndarray
    unit_ids: np.ndarray


_RATIO_UNITS: dict[MetricId, MetricUnit] = {
    MetricId.tool_error_rate: MetricUnit.rate,
    MetricId.tool_retry_rate: MetricUnit.rate,
    MetricId.loop_rate: MetricUnit.rate,
    MetricId.tool_calls_per_turn: MetricUnit.count_,
    MetricId.zero_tool_turn_rate: MetricUnit.rate,
    MetricId.llm_error_rate: MetricUnit.rate,
    MetricId.format_failure_rate: MetricUnit.rate,
    MetricId.cost_per_turn: MetricUnit.usd,
    MetricId.turns_per_session: MetricUnit.count_,
}


def agent_metric_settings(agent: Agent) -> dict[MetricId, MetricSettings]:
    settings = effective_metric_settings(agent.metric_settings)
    if agent.output_format is not OutputFormat.json:
        settings.pop(MetricId.format_failure_rate, None)
    return settings


def specs_for(settings: dict[MetricId, MetricSettings]) -> list[MetricSpec]:
    built: list[MetricSpec] = []
    for metric_id in MetricId:
        metric_settings = settings.get(metric_id)
        if metric_settings is None:
            continue
        if metric_id is MetricId.latency_p95:
            built.append(
                MetricSpec(
                    metric_id,
                    METRIC_LEVELS[metric_id],
                    metric_settings,
                    MetricUnit.ms,
                    "percentile",
                    0.95,
                )
            )
            continue
        if metric_id is MetricId.output_tokens_p50:
            built.append(
                MetricSpec(
                    metric_id,
                    METRIC_LEVELS[metric_id],
                    metric_settings,
                    MetricUnit.tokens,
                    "percentile",
                    0.5,
                )
            )
            continue
        built.append(
            MetricSpec(
                metric_id,
                METRIC_LEVELS[metric_id],
                metric_settings,
                _RATIO_UNITS[metric_id],
                "ratio",
                None,
            )
        )
    return built


def default_specs() -> list[MetricSpec]:
    return specs_for(DEFAULT_METRICS)


def _sessions(turns: list[ArmTurn]) -> dict[str, int]:
    ordered = sorted({turn.session_id for turn in turns})
    return {session_id: index for index, session_id in enumerate(ordered)}


def session_index(arm: ArmData) -> dict[str, int]:
    return _sessions(arm.turns)


def point_ratio(num: np.ndarray, den: np.ndarray) -> float:
    total = float(np.sum(den))
    if total == 0:
        return float("nan")
    return float(np.sum(num) / total)


def point_quantile(values: np.ndarray, quantile: float) -> float:
    if values.size == 0:
        return float("nan")
    return float(np.quantile(values, quantile, method="inverted_cdf"))


def _empty() -> UnitArrays:
    return UnitArrays(
        num=np.zeros(0, dtype=np.float64),
        den=np.zeros(0, dtype=np.float64),
        values=np.zeros(0, dtype=np.float64),
        session_idx=np.zeros(0, dtype=np.int64),
        unit_ids=np.zeros(0, dtype=np.int64),
    )


def _ratio(num: list[float], den: list[float], sessions: list[int]) -> UnitArrays:
    return UnitArrays(
        num=np.asarray(num, dtype=np.float64),
        den=np.asarray(den, dtype=np.float64),
        values=np.zeros(0, dtype=np.float64),
        session_idx=np.asarray(sessions, dtype=np.int64),
        unit_ids=np.arange(len(num), dtype=np.int64),
    )


def _values(values: list[float], sessions: list[int]) -> UnitArrays:
    return UnitArrays(
        num=np.zeros(0, dtype=np.float64),
        den=np.zeros(0, dtype=np.float64),
        values=np.asarray(values, dtype=np.float64),
        session_idx=np.asarray(sessions, dtype=np.int64),
        unit_ids=np.arange(len(values), dtype=np.int64),
    )


def unit_arrays(
    spec: MetricSpec,
    arm: ArmData,
    unit: MetricUnit,
    *,
    turns: list[ArmTurn] | None = None,
    tools: list[ArmToolCall] | None = None,
    sessions: dict[str, int] | None = None,
) -> UnitArrays:
    population = arm.turns if turns is None else turns
    tool_rows = arm.tool_calls if tools is None else tools
    index = session_index(arm) if sessions is None else sessions
    if spec.id is MetricId.tool_error_rate:
        return _ratio(
            [1.0 if tool.is_error else 0.0 for tool in tool_rows],
            [1.0 for _tool in tool_rows],
            [index.get(tool.session_id, 0) for tool in tool_rows],
        )
    if spec.id is MetricId.tool_retry_rate:
        num: list[float] = []
        den: list[float] = []
        owners: list[int] = []
        for tool in tool_rows:
            if not tool.has_args_hash:
                continue
            num.append(1.0 if tool.is_retry is True else 0.0)
            den.append(1.0)
            owners.append(index.get(tool.session_id, 0))
        return _ratio(num, den, owners)
    if spec.id is MetricId.turns_per_session:
        grouped: dict[str, list[ArmTurn]] = {}
        for turn in population:
            grouped.setdefault(turn.session_id, []).append(turn)
        closed = [
            (session_id, rows)
            for session_id, rows in grouped.items()
            if rows and rows[0].session_closed
        ]
        return _ratio(
            [float(len(rows)) for _session, rows in closed],
            [1.0 for _session in closed],
            [index.get(session_id, 0) for session_id, _rows in closed],
        )
    if spec.kind == "percentile" and spec.id is MetricId.output_tokens_p50:
        values: list[float] = []
        owners = []
        for turn in population:
            raw = turn.output_tokens if unit is MetricUnit.tokens else turn.output_chars
            if raw is None:
                continue
            values.append(float(raw))
            owners.append(index.get(turn.session_id, 0))
        return _values(values, owners)
    if spec.kind == "percentile":
        return _values(
            [float(turn.latency_ms) for turn in population],
            [index.get(turn.session_id, 0) for turn in population],
        )
    num_rows: list[float] = []
    den_rows: list[float] = []
    owners = []
    for turn in population:
        owner = index.get(turn.session_id, 0)
        if spec.id is MetricId.loop_rate:
            if turn.loop_flag is None:
                continue
            num_rows.append(1.0 if turn.loop_flag else 0.0)
            den_rows.append(1.0)
        elif spec.id is MetricId.tool_calls_per_turn:
            num_rows.append(float(turn.tool_calls))
            den_rows.append(1.0)
        elif spec.id is MetricId.zero_tool_turn_rate:
            num_rows.append(1.0 if turn.zero_tool else 0.0)
            den_rows.append(1.0)
        elif spec.id is MetricId.llm_error_rate:
            num_rows.append(1.0 if turn.llm_error else 0.0)
            den_rows.append(1.0)
        elif spec.id is MetricId.format_failure_rate:
            if turn.format_ok is None:
                continue
            num_rows.append(1.0 if turn.format_ok is False else 0.0)
            den_rows.append(1.0)
        elif spec.id is MetricId.cost_per_turn:
            if turn.cost_usd is None:
                continue
            num_rows.append(float(turn.cost_usd))
            den_rows.append(1.0)
        else:
            continue
        owners.append(owner)
    if not num_rows:
        return _empty()
    return _ratio(num_rows, den_rows, owners)


def session_sums(arrays: UnitArrays, n_sessions: int) -> tuple[np.ndarray, np.ndarray]:
    num = np.zeros(n_sessions, dtype=np.float64)
    den = np.zeros(n_sessions, dtype=np.float64)
    if arrays.session_idx.size == 0 or n_sessions == 0:
        return num, den
    if arrays.num.size:
        np.add.at(num, arrays.session_idx, arrays.num)
        np.add.at(den, arrays.session_idx, arrays.den)
    return num, den
