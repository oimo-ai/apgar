from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from itertools import takewhile

from apgar.domain.enums import MetricId, ReasonCode, ReleaseEventType, VerdictState
from apgar.domain.models import ReleaseEvent, VerdictEvaluation
from apgar.domain.settings import VerdictSettings


@dataclass(slots=True)
class ReleaseUserState:
    manual_baseline: str | None
    expected_changes: frozenset[MetricId]
    changed_at: datetime | None = None
    stopped_at: datetime | None = None


@dataclass(slots=True)
class Outcome:
    any_fail: bool
    all_pass: bool


def fold_events(events: list[ReleaseEvent]) -> ReleaseUserState:
    ordered = sorted(events, key=lambda event: (event.ts, event.type.value))
    manual: str | None = None
    expected: frozenset[MetricId] = frozenset()
    changed_at: datetime | None = None
    stopped_at: datetime | None = None
    for event in ordered:
        if event.type is ReleaseEventType.manual_baseline:
            manual = str(event.payload.get("release", "")) or None
            changed_at = event.ts
        elif event.type is ReleaseEventType.expected_changes:
            metrics = event.payload.get("metrics", [])
            parsed: set[MetricId] = set()
            for item in metrics:
                try:
                    parsed.add(MetricId(str(item)))
                except ValueError:
                    continue
            expected = frozenset(parsed)
            changed_at = event.ts
        elif event.type is ReleaseEventType.stop and stopped_at is None:
            stopped_at = event.ts
    return ReleaseUserState(manual, expected, changed_at, stopped_at)


def reopens_fail(
    state: VerdictState, verdict_updated_at: datetime | None, user_state: ReleaseUserState
) -> bool:
    # A FAIL holds until the baseline or the expected changes change after it was decided.
    changed = user_state.changed_at
    if state is not VerdictState.FAIL or changed is None:
        return False
    return verdict_updated_at is None or changed > verdict_updated_at


def confirmation_run(
    prev_evals: list[VerdictEvaluation], baseline: str, user_state: ReleaseUserState
) -> list[VerdictEvaluation]:
    changed = user_state.changed_at
    return list(
        takewhile(
            lambda item: (
                item.baseline_release == baseline
                and (changed is None or item.evaluated_at > changed)
            ),
            prev_evals,
        )
    )


def consecutive(
    prev_evals: list[VerdictEvaluation],
    current_at: datetime,
    flag: str,
    k: int,
    gap_minutes: int,
) -> bool:
    if k <= 1:
        return True
    earlier = [item for item in prev_evals if item.evaluated_at < current_at]
    streak = list(takewhile(lambda item: item.metrics.get(flag) is True, earlier))
    if len(streak) < k - 1:
        return False
    return current_at - streak[-1].evaluated_at >= timedelta(minutes=gap_minutes)


def history_limit(vs: VerdictSettings) -> int:
    return max(vs.fail_confirmations, vs.pass_confirmations, 1) + 12


def _finalize(
    state: VerdictState, reason: ReasonCode, ended: ReasonCode | None
) -> tuple[VerdictState, ReasonCode, bool]:
    if ended is None:
        return state, reason, False
    if state in {VerdictState.PENDING, VerdictState.INCONCLUSIVE}:
        return VerdictState.INCONCLUSIVE, ended, True
    return state, reason, True


def next_state(
    prev_state: VerdictState,
    prev_reason: ReasonCode,
    prev_evals: list[VerdictEvaluation],
    current_at: datetime,
    outcome: Outcome | None,
    ended: ReasonCode | None,
    vs: VerdictSettings,
    direct: tuple[VerdictState, ReasonCode] | None = None,
    *,
    reopen: bool = False,
) -> tuple[VerdictState, ReasonCode, bool]:
    if prev_state is VerdictState.FAIL and not reopen:
        return _finalize(VerdictState.FAIL, ReasonCode.confirmed, ended)
    if outcome is None:
        state, reason = (prev_state, prev_reason) if direct is None else direct
        return _finalize(state, reason, ended)
    # The final check runs on a frozen window, so repeating it cannot change the outcome.
    final_check = ended is not None
    if outcome.any_fail:
        if final_check or consecutive(
            prev_evals, current_at, "any_fail", vs.fail_confirmations, vs.confirmation_gap_minutes
        ):
            state, reason = VerdictState.FAIL, ReasonCode.confirmed
        else:
            state, reason = VerdictState.INCONCLUSIVE, ReasonCode.fail_candidate
    elif outcome.all_pass:
        if final_check or consecutive(
            prev_evals, current_at, "all_pass", vs.pass_confirmations, vs.confirmation_gap_minutes
        ):
            state, reason = VerdictState.PASS, ReasonCode.confirmed
        else:
            state, reason = VerdictState.INCONCLUSIVE, ReasonCode.pass_candidate
    else:
        state, reason = VerdictState.INCONCLUSIVE, ReasonCode.insufficient_power
    if (
        prev_state is VerdictState.PASS
        and state is VerdictState.INCONCLUSIVE
        and reason
        in {
            ReasonCode.insufficient_power,
            ReasonCode.pass_candidate,
        }
    ):
        state, reason = VerdictState.PASS, prev_reason
    return _finalize(state, reason, ended)
