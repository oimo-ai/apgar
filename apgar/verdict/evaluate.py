from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Any

import numpy as np
from prometheus_client import Counter

from apgar.config import Settings
from apgar.domain.enums import (
    Direction,
    MetricId,
    MetricRole,
    MetricStatus,
    ReasonCode,
    ToleranceMode,
    VerdictState,
)
from apgar.domain.models import Agent, Release, VerdictEvaluation
from apgar.domain.settings import MetricSettings, VerdictSettings
from apgar.domain.time import monotonic_updated_at, to_iso
from apgar.storage.interfaces import EventStore, MetaStore
from apgar.storage.types import ArmData, ArmQuery, ReleaseActivity, ReleaseFilters
from apgar.verdict.applicability import Applicability, assess
from apgar.verdict.baseline import BaselineChoice, select_baseline
from apgar.verdict.bootstrap import (
    BootstrapJob,
    ColumnResult,
    run_bootstrap,
)
from apgar.verdict.metrics import (
    MetricSpec,
    agent_metric_settings,
    point_quantile,
    point_ratio,
    session_index,
    specs_for,
    unit_arrays,
)
from apgar.verdict.numbers import finite
from apgar.verdict.pool import EvaluatorPool, InlinePool
from apgar.verdict.power import delta_oriented, orient, power, status
from apgar.verdict.slices import (
    SliceCell,
    apply_slice_results,
    comparison_column,
    ordered_cells,
    prepare_slices,
)
from apgar.verdict.state_machine import (
    Outcome,
    ReleaseUserState,
    confirmation_run,
    fold_events,
    history_limit,
    next_state,
    reopens_fail,
)
from apgar.verdict.summary import build_summary

_LOG = logging.getLogger("apgar.verdict")
EVAL_ERRORS = Counter(
    "apgar_evaluation_errors_total",
    "Evaluations that raised before writing a release row.",
    ["agent"],
)


@dataclass(slots=True)
class TransitionEvent:
    agent: Agent
    release: Release
    prev_state: VerdictState
    prev_reason: ReasonCode
    new_state: VerdictState
    new_reason: ReasonCode
    evaluation: VerdictEvaluation
    final_flag: bool
    became_final: bool


@dataclass(frozen=True, slots=True)
class EndOfMonitoring:
    reason: ReasonCode
    by: str | None


def monitoring_cap(release: Release, vs: VerdictSettings, user_state: ReleaseUserState) -> datetime:
    cap = release.first_seen + timedelta(hours=vs.max_window_hours)
    if user_state.stopped_at is not None:
        return min(cap, user_state.stopped_at)
    return cap


def end_of_monitoring(
    release: Release,
    releases: list[Release],
    now: datetime,
    cap: datetime,
    stopped_at: datetime | None = None,
) -> EndOfMonitoring | None:
    if stopped_at is not None and stopped_at <= min(now, cap):
        return EndOfMonitoring(ReasonCode.stopped, None)
    if now >= cap:
        return EndOfMonitoring(ReasonCode.window_elapsed, None)
    newer = [
        row
        for row in releases
        if release.first_seen < row.first_seen <= now
        and row.release not in {release.release, "untagged"}
    ]
    if not newer:
        return None
    successor = min(newer, key=lambda row: (row.first_seen, row.release))
    return EndOfMonitoring(ReasonCode.superseded, successor.release)


def least_sensitive(guard: list[MetricSpec], items: dict[str, Any]) -> str | None:
    ranked: list[tuple[float, str]] = []
    for spec in guard:
        detectable = finite(items.get(spec.id.value, {}).get("detectable_degradation"))
        if detectable is not None:
            ranked.append((abs(detectable) / spec.settings.tolerance, spec.id.value))
    if ranked:
        return max(ranked)[1]
    return next((spec.id.value for spec in guard), None)


def evaluation_seed(agent_id: str, release: str, window_end: datetime) -> tuple[int, str]:
    seed_hex = hashlib.sha256(f"{agent_id}{release}{to_iso(window_end)}".encode()).hexdigest()[:8]
    return int(seed_hex, 16), seed_hex


def _sessions(arm: ArmData) -> int:
    return len({turn.session_id for turn in arm.turns})


def _shell(
    *,
    alpha: float | None,
    guard_count: int,
    headline: str | None,
    turns_needed: int | None,
    items: dict[str, Any],
    any_fail: bool,
    all_pass: bool,
    early: bool = False,
) -> dict[str, Any]:
    return {
        "any_fail": any_fail,
        "all_pass": all_pass,
        "early": early,
        "alpha_adjusted": alpha,
        "guard_count": guard_count,
        "headline_metric": headline,
        "sample": {"turns_needed": turns_needed},
        "items": items,
    }


def _delta(point_c: float | None, point_b: float | None, relative: bool) -> float | None:
    if point_c is None or point_b is None:
        return None
    if relative:
        if point_b == 0:
            return None
        return (point_c - point_b) / point_b
    return point_c - point_b


def _trend(
    direction: Direction, delta: float | None, previous: float | None, tau: float
) -> str | None:
    if delta is None or previous is None:
        return None
    change = delta_oriented(direction, delta) - delta_oriented(direction, previous)
    if change > 0.1 * tau:
        return "worsening"
    if change < -0.1 * tau:
        return "improving"
    return "flat"


def _na_item(spec: MetricSpec, decision: Applicability) -> dict[str, Any]:
    return {
        "level": spec.level.value,
        "role": spec.settings.role.value,
        "direction": spec.settings.direction.value,
        "tolerance_mode": spec.settings.tolerance_mode.value,
        "tolerance": spec.settings.tolerance,
        "unit": decision.unit.value,
        "applicable": False,
        "na_reason": decision.na_reason,
        "coverage": decision.coverage,
        "baseline": None,
        "candidate": None,
        "delta": None,
        "ci": None,
        "status": MetricStatus.NA.value,
        "turns_needed": None,
        "detectable_degradation": None,
        "n_candidate_units": 0,
        "n_baseline_units": 0,
        "trend": None,
    }


def _point(spec: MetricSpec, arm: ArmData, decision: Applicability) -> float | None:
    if not arm.turns:
        return None
    arrays = unit_arrays(spec, arm, decision.unit)
    if spec.kind == "percentile":
        assert spec.quantile is not None
        return finite(point_quantile(arrays.values, spec.quantile))
    return finite(point_ratio(arrays.num, arrays.den))


def raw_items(
    cand: ArmData, base: ArmData, metric_settings: dict[MetricId, MetricSettings]
) -> dict[str, Any]:
    reference = base if base.turns else cand
    items: dict[str, Any] = {}
    for spec in specs_for(metric_settings):
        decision = assess(spec, cand.turns, cand.tool_calls, reference.turns, reference.tool_calls)
        item = _na_item(spec, decision)
        if decision.applicable:
            item.update(
                applicable=True,
                status=MetricStatus.INCONCLUSIVE.value,
                candidate=_point(spec, cand, decision),
                baseline=_point(spec, base, decision),
            )
        items[spec.id.value] = item
    return items


@dataclass(slots=True)
class Prepared:
    job: BootstrapJob | None
    specs: list[MetricSpec]
    decisions: dict[str, Applicability]
    guard: list[MetricSpec]
    alpha: float
    cells: dict[str, dict[str, list[SliceCell]]]
    n_turns: int


def prepare_analysis(
    cand: ArmData,
    base: ArmData,
    metric_settings: dict[MetricId, MetricSettings],
    vs: VerdictSettings,
    expected: frozenset[MetricId],
    *,
    resamples: int,
    chunk: int,
    seed: int,
) -> Prepared:
    built = specs_for(metric_settings)
    decisions = {
        spec.id.value: assess(spec, cand.turns, cand.tool_calls, base.turns, base.tool_calls)
        for spec in built
    }
    guard = [
        spec
        for spec in built
        if spec.settings.role is MetricRole.guardrail
        and decisions[spec.id.value].applicable
        and spec.id not in expected
    ]
    guard_count = len(guard)
    alpha = vs.alpha / max(1, guard_count)
    sessions_c = session_index(cand)
    sessions_b = session_index(base)
    columns: list[Any] = []
    for spec in built:
        decision = decisions[spec.id.value]
        if not decision.applicable:
            continue
        columns.append(
            comparison_column(
                spec,
                cand,
                base,
                cand.turns,
                cand.tool_calls,
                base.turns,
                base.tool_calls,
                decision.unit,
                (spec.id.value, "", ""),
                sessions_c,
                sessions_b,
                len(sessions_c),
                len(sessions_b),
            )
        )
    cells: dict[str, dict[str, list[SliceCell]]] = {}
    if sessions_c and sessions_b:
        applicable = [spec for spec in built if decisions[spec.id.value].applicable]
        cells, slice_columns = prepare_slices(applicable, cand, base, vs, sessions_c, sessions_b)
        columns.extend(slice_columns)
    else:
        cells = {spec.id.value: {} for spec in built}
    ratio = [column for column in columns if hasattr(column, "xc")]
    percentile = [column for column in columns if hasattr(column, "vc")]
    job = None
    if columns and sessions_c and sessions_b:
        job = BootstrapJob(
            seed,
            resamples,
            chunk,
            len(sessions_c),
            len(sessions_b),
            ratio,
            percentile,
        )
    return Prepared(job, built, decisions, guard, alpha, cells, len(cand.turns))


def interpret(
    prepared: Prepared,
    results: list[ColumnResult],
    cand: ArmData,
    base: ArmData,
    previous: dict[str, Any] | None,
) -> tuple[dict[str, Any], dict[str, Any], Outcome]:
    by_key = {result.key: result for result in results}
    items: dict[str, Any] = {}
    n_turns = len(cand.turns)
    for spec in prepared.specs:
        decision = prepared.decisions[spec.id.value]
        if not decision.applicable:
            items[spec.id.value] = _na_item(spec, decision)
            continue
        result = by_key.get((spec.id.value, "", ""))
        relative = spec.settings.tolerance_mode is ToleranceMode.rel
        alpha = prepared.alpha
        point_c = None if result is None else finite(result.point_c)
        point_b = None if result is None else finite(result.point_b)
        delta = _delta(point_c, point_b, relative)
        ci = None
        metric_status = MetricStatus.NA
        na_reason = decision.na_reason
        turns_needed = None
        detectable = None
        applicable = True
        if result is None or delta is None:
            applicable = False
            na_reason = "zero_denominator"
            metric_status = MetricStatus.NA
        else:
            from apgar.verdict.bootstrap import interval

            lower, upper, se, share = interval(result.diffs, alpha)
            if share < 0.5 or not math_ok(lower) or not math_ok(upper):
                applicable = False
                na_reason = "zero_denominator"
                metric_status = MetricStatus.NA
                delta = None
                point_c = None
                point_b = None
            else:
                ci = [lower, upper]
                oriented = orient(spec.settings.direction, lower, upper)
                metric_status = status(
                    spec.settings.direction, oriented[0], oriented[1], spec.settings.tolerance
                )
                turns_needed, detectable = power(n_turns, se, spec.settings.tolerance, alpha)
        if spec.id in _expected_ids(prepared) and applicable:
            metric_status = MetricStatus.EXPECTED
        prev_delta = None
        if previous is not None:
            prev_item = previous.get(spec.id.value)
            if isinstance(prev_item, dict):
                prev_delta = finite(prev_item.get("delta"))
        trend = _trend(spec.settings.direction, delta, prev_delta, spec.settings.tolerance)
        n_units, n_base_units = _unit_counts(prepared, (spec.id.value, "", ""))
        items[spec.id.value] = {
            "level": spec.level.value,
            "role": spec.settings.role.value,
            "direction": spec.settings.direction.value,
            "tolerance_mode": spec.settings.tolerance_mode.value,
            "tolerance": spec.settings.tolerance,
            "unit": decision.unit.value,
            "applicable": applicable and decision.applicable,
            "na_reason": None if applicable else na_reason,
            "coverage": decision.coverage,
            "baseline": point_b,
            "candidate": point_c,
            "delta": delta,
            "ci": ci,
            "status": metric_status.value,
            "turns_needed": turns_needed,
            "detectable_degradation": detectable,
            "n_candidate_units": n_units,
            "n_baseline_units": n_base_units,
            "trend": trend if applicable else None,
        }
    slices = _slice_json(prepared, by_key)
    guard_items = [items[spec.id.value] for spec in prepared.guard]
    any_fail = any(item["status"] == MetricStatus.FAIL.value for item in guard_items)
    all_pass = bool(guard_items) and all(
        item["status"] == MetricStatus.PASS.value for item in guard_items
    )
    return items, slices, Outcome(any_fail, all_pass)


def _expected_ids(prepared: Prepared) -> set[MetricId]:
    return set()


def math_ok(value: float) -> bool:
    return finite(value) is not None


def _slice_json(
    prepared: Prepared, by_key: dict[tuple[str, str, str], ColumnResult]
) -> dict[str, Any]:
    if not prepared.cells:
        return {}
    specs = {spec.id.value: spec for spec in prepared.specs}
    diffs = {key: result.diffs for key, result in by_key.items() if key[1] != ""}
    apply_slice_results(prepared.cells, specs, diffs)
    payload: dict[str, Any] = {}
    for metric, dimensions in prepared.cells.items():
        spec = specs[metric]
        block: dict[str, Any] = {}
        for dimension, cells in dimensions.items():
            applicable = bool(cells)
            ordered = ordered_cells(cells, spec.settings.direction)
            block[dimension] = {
                "applicable": applicable,
                "values": [_cell_json(cell) for cell in ordered],
            }
        for dimension in (
            "tool",
            "surface",
            "session_depth",
            "response_model",
            "prompt_version",
        ):
            block.setdefault(dimension, {"applicable": False, "values": []})
        payload[metric] = block
    return payload


def _cell_json(cell: SliceCell) -> dict[str, Any]:
    return {
        "value": cell.value,
        "candidate": finite(cell.candidate),
        "baseline": finite(cell.baseline),
        "delta": finite(cell.delta),
        "ci": None if cell.ci is None else [finite(cell.ci[0]), finite(cell.ci[1])],
        "p_value": finite(cell.p_value),
        "p_adjusted": finite(cell.p_adjusted),
        "status": cell.status.value,
        "n_candidate": cell.n_candidate,
        "n_baseline": cell.n_baseline,
        "reason": cell.reason,
    }


class Evaluator:
    def __init__(
        self,
        event_store: EventStore,
        meta_store: MetaStore,
        settings: Settings,
        pool: EvaluatorPool | InlinePool,
        clock: Callable[[], datetime],
        on_transition: list[Callable[[TransitionEvent], Awaitable[None]]],
        release_lock: asyncio.Lock,
    ) -> None:
        self._events = event_store
        self._meta = meta_store
        self._settings = settings
        self._pool = pool
        self._clock = clock
        self.on_transition = on_transition
        self._lock = release_lock

    async def evaluate_release(
        self,
        agent: Agent,
        release: Release,
        now: datetime,
        manual: bool,
        *,
        notify: bool = True,
    ) -> VerdictEvaluation:
        try:
            return await self._evaluate(agent, release, now, manual, notify=notify)
        except Exception:
            EVAL_ERRORS.labels(agent=agent.name).inc()
            _LOG.exception(
                "evaluation failed",
                extra={"agent": agent.name, "release": release.release},
            )
            raise

    async def _evaluate(
        self,
        agent: Agent,
        release: Release,
        now: datetime,
        manual: bool,
        *,
        notify: bool = True,
    ) -> VerdictEvaluation:
        started = time.perf_counter()
        vs = agent.verdict_settings
        events = await self._meta.release_events(agent.id, release.release)
        user_state = fold_events(events)
        cap = monitoring_cap(release, vs, user_state)
        window_end = min(now, cap)
        _seed, seed_hex = evaluation_seed(agent.id, release.release, window_end)
        releases = await self._meta.list_releases(
            ReleaseFilters(agent_id=agent.id, limit=100_000, offset=0)
        )
        activity = _activity(await self._events.release_activity(agent.id, agent.environment))
        ended = end_of_monitoring(release, releases, now, cap, user_state.stopped_at)
        choice = select_baseline(release, releases, user_state, activity, window_end)
        metric_settings = agent_metric_settings(agent)
        if choice is None:
            cand = await self._events.load_arm(
                _arm_query(
                    agent,
                    release.release,
                    release.first_seen,
                    window_end,
                    now,
                    hours=None,
                    count_untagged=True,
                    include_mixed=vs.include_mixed_sessions,
                )
            )
            empty = ArmData([], [], 0, 0, 0)
            return await self._finish(
                agent,
                release,
                now,
                manual,
                seed_hex,
                None,
                window_end,
                ended,
                user_state,
                VerdictState.PENDING,
                ReasonCode.no_baseline,
                _shell(
                    alpha=None,
                    guard_count=0,
                    headline=None,
                    turns_needed=None,
                    items=raw_items(cand, empty, metric_settings),
                    any_fail=False,
                    all_pass=False,
                ),
                {},
                (cand, empty),
                started,
                notify=notify,
            )
        cand = await self._events.load_arm(
            _arm_query(
                agent,
                release.release,
                release.first_seen,
                window_end,
                now,
                hours=None,
                count_untagged=True,
                include_mixed=vs.include_mixed_sessions,
            )
        )
        base = await self._events.load_arm(
            _arm_query(
                agent,
                choice.release,
                choice.window_start,
                choice.window_end,
                now,
                hours=choice.hour_of_day_filter,
                count_untagged=False,
                include_mixed=vs.include_mixed_sessions,
            )
        )
        floor_turns, floor_sessions = vs.early_floor
        cand_turns, cand_sessions = len(cand.turns), _sessions(cand)
        if cand_turns < floor_turns or cand_sessions < floor_sessions:
            return await self._finish(
                agent,
                release,
                now,
                manual,
                seed_hex,
                choice,
                window_end,
                ended,
                user_state,
                VerdictState.PENDING,
                ReasonCode.insufficient_sample,
                _population_shell(
                    cand,
                    base,
                    max(0, vs.min_turns - len(cand.turns)),
                    raw_items(cand, base, metric_settings),
                ),
                {},
                (cand, base),
                started,
                notify=notify,
            )
        if len(base.turns) < vs.min_turns or _sessions(base) < vs.min_sessions:
            return await self._finish(
                agent,
                release,
                now,
                manual,
                seed_hex,
                choice,
                window_end,
                ended,
                user_state,
                VerdictState.PENDING,
                ReasonCode.insufficient_baseline,
                _population_shell(cand, base, None, raw_items(cand, base, metric_settings)),
                {},
                (cand, base),
                started,
                notify=notify,
            )
        prepared = prepare_analysis(
            cand,
            base,
            metric_settings,
            vs,
            user_state.expected_changes,
            resamples=self._settings.bootstrap_resamples,
            chunk=self._settings.bootstrap_chunk,
            seed=_seed,
        )
        prepared_expected = user_state.expected_changes
        results = await self._pool.run(run_bootstrap, prepared.job) if prepared.job else []
        prev = await self._meta.list_evaluations(agent.id, release.release, limit=history_limit(vs))
        prev = [item for item in prev if item.evaluated_at < now]
        previous_items = prev[0].metrics.get("items") if prev else None
        items, slices, outcome = interpret(
            prepared,
            results,
            cand,
            base,
            previous_items if isinstance(previous_items, dict) else None,
        )
        _mark_expected(items, prepared_expected)
        outcome = _outcome(prepared.guard, items)
        below_minimum = cand_turns < vs.min_turns or cand_sessions < vs.min_sessions
        collecting = below_minimum and not outcome.any_fail
        if collecting:
            outcome = Outcome(False, False)
        failed_early = (
            release.state is VerdictState.FAIL
            and not reopens_fail(release.state, release.verdict_updated_at, user_state)
            and bool(release.verdict_summary.get("early"))
        )
        early = (below_minimum and outcome.any_fail) or failed_early
        metrics = _shell(
            alpha=prepared.alpha,
            guard_count=len(prepared.guard),
            headline=least_sensitive(prepared.guard, items),
            turns_needed=max(0, vs.min_turns - cand_turns) if below_minimum else None,
            items=items,
            any_fail=outcome.any_fail,
            all_pass=outcome.all_pass,
            early=early,
        )
        return await self._finish(
            agent,
            release,
            now,
            manual,
            seed_hex,
            choice,
            window_end,
            ended,
            user_state,
            VerdictState.PENDING if collecting else None,
            ReasonCode.insufficient_sample if collecting else None,
            metrics,
            slices,
            (cand, base),
            started,
            outcome=None if collecting else outcome,
            prev=prev,
            notify=notify,
        )

    async def _finish(
        self,
        agent: Agent,
        release: Release,
        now: datetime,
        manual: bool,
        seed_hex: str,
        choice: BaselineChoice | None,
        window_end: datetime,
        ended: EndOfMonitoring | None,
        user_state: ReleaseUserState,
        direct_state: VerdictState | None,
        direct_reason: ReasonCode | None,
        metrics: dict[str, Any],
        slices: dict[str, Any],
        arms: tuple[ArmData, ArmData] | None,
        started: float,
        outcome: Outcome | None = None,
        prev: list[VerdictEvaluation] | None = None,
        notify: bool = True,
    ) -> VerdictEvaluation:
        vs = agent.verdict_settings
        if prev is None:
            prev = await self._meta.list_evaluations(
                agent.id, release.release, limit=history_limit(vs)
            )
            prev = [item for item in prev if item.evaluated_at < now]
        if ended is not None:
            metrics = {**metrics, "ended": {"reason": ended.reason.value, "by": ended.by}}
        direct = None
        if direct_state is not None and direct_reason is not None:
            direct = (direct_state, direct_reason)
            outcome = None
        cand_turns = 0 if arms is None else len(arms[0].turns)
        base_turns = 0 if arms is None else len(arms[1].turns)
        cand_sessions = 0 if arms is None else _sessions(arms[0])
        base_sessions = 0 if arms is None else _sessions(arms[1])
        excluded_mixed = 0 if arms is None else arms[0].n_excluded_mixed
        excluded_late = 0 if arms is None else arms[0].n_excluded_late
        excluded_untagged = 0 if arms is None else arms[0].n_excluded_untagged
        window_start = release.first_seen if choice is not None else None
        evaluation = VerdictEvaluation(
            agent_id=agent.id,
            release=release.release,
            evaluated_at=now,
            manual=manual,
            seed=seed_hex,
            baseline_release="" if choice is None else choice.release,
            baseline_mode="" if choice is None else choice.reported_mode,
            baseline_unverified=False if choice is None else choice.unverified,
            window_start=window_start,
            window_end=window_end,
            n_candidate_turns=cand_turns,
            n_baseline_turns=base_turns,
            n_candidate_sessions=cand_sessions,
            n_baseline_sessions=base_sessions,
            n_excluded_mixed=excluded_mixed,
            n_excluded_untagged=excluded_untagged,
            n_excluded_late=excluded_late,
            state=release.state,
            reason=release.reason,
            final=release.final,
            metrics=metrics,
            slices=slices,
            duration_ms=int((time.perf_counter() - started) * 1000),
        )
        async with self._lock:
            current = await self._meta.get_release(agent.id, release.release)
            if current is None:
                current = release
            fresh_prev = await self._meta.list_evaluations(
                agent.id, release.release, limit=history_limit(vs)
            )
            prev = [item for item in fresh_prev if item.evaluated_at < now]
            run = confirmation_run(prev, evaluation.baseline_release, user_state)
            state, reason, final_flag = next_state(
                current.state,
                current.reason,
                run,
                now,
                outcome,
                None if ended is None else ended.reason,
                vs,
                direct,
                reopen=reopens_fail(current.state, current.verdict_updated_at, user_state),
            )
            prev_state, prev_reason = current.state, current.reason
            was_final = current.final
            evaluation = replace(
                evaluation,
                state=state,
                reason=reason,
                final=final_flag,
            )
            stored = replace(
                current,
                state=state,
                reason=reason,
                final=final_flag,
                final_at=now if final_flag and not current.final else current.final_at,
                selected_baseline_release="" if choice is None else choice.release,
                selected_baseline_mode="" if choice is None else choice.reported_mode,
                baseline_unverified=False if choice is None else choice.unverified,
                verdict_updated_at=now,
                updated_at=monotonic_updated_at(max(now, self._clock()), current.updated_at),
            )
            summary = build_summary(agent, stored, evaluation, self._settings)
            stored = replace(stored, verdict_summary=summary)
            await self._meta.append_evaluation(evaluation)
            await self._meta.upsert_release(stored)
            release_row = stored
        became_final = final_flag and not was_final
        event = TransitionEvent(
            agent,
            release_row,
            prev_state,
            prev_reason,
            state,
            reason,
            evaluation,
            final_flag,
            became_final,
        )
        if notify:
            for hook in self.on_transition:
                try:
                    await hook(event)
                except Exception:
                    _LOG.exception(
                        "transition hook failed",
                        extra={"agent": agent.name, "release": release.release},
                    )
        return evaluation


def _unit_counts(prepared: Prepared, key: tuple[str, str, str]) -> tuple[int, int]:
    if prepared.job is None:
        return 0, 0
    for column in prepared.job.ratio:
        if column.key == key:
            return int(np.sum(column.dc)), int(np.sum(column.db))
    for pct in prepared.job.percentile:
        if pct.key == key:
            return int(pct.vc.size), int(pct.vb.size)
    return 0, 0


def _mark_expected(items: dict[str, Any], expected: frozenset[MetricId]) -> None:
    for metric_id in expected:
        item = items.get(metric_id.value)
        if isinstance(item, dict) and item.get("applicable"):
            item["status"] = MetricStatus.EXPECTED.value


def _outcome(guard: list[MetricSpec], items: dict[str, Any]) -> Outcome:
    guard_items = [items[spec.id.value] for spec in guard if spec.id.value in items]
    any_fail = any(item.get("status") == MetricStatus.FAIL.value for item in guard_items)
    all_pass = bool(guard_items) and all(
        item.get("status") == MetricStatus.PASS.value for item in guard_items
    )
    return Outcome(any_fail, all_pass)


def _population_shell(
    cand: ArmData, base: ArmData, turns_needed: int | None, items: dict[str, Any]
) -> dict[str, Any]:
    return _shell(
        alpha=None,
        guard_count=0,
        headline=None,
        turns_needed=turns_needed,
        items=items,
        any_fail=False,
        all_pass=False,
    )


def _arm_query(
    agent: Agent,
    release: str,
    start: datetime,
    end: datetime,
    now: datetime,
    *,
    hours: frozenset[int] | None,
    count_untagged: bool,
    include_mixed: bool,
) -> ArmQuery:
    return ArmQuery(
        agent_id=agent.id,
        release=release,
        window_start=start,
        window_end=end,
        environment=agent.environment,
        include_mixed=include_mixed,
        session_min_first_start=None,
        hour_of_day_filter=hours,
        now=now,
        count_untagged=count_untagged,
    )


def _activity(rows: list[ReleaseActivity]) -> dict[str, ReleaseActivity]:
    return {row.release: row for row in rows}
