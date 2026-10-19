from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from apgar.domain.enums import MetricId, ReasonCode, ReleaseEventType, VerdictState
from apgar.domain.models import ReleaseEvent, VerdictEvaluation
from apgar.domain.settings import VerdictSettings
from apgar.verdict.state_machine import (
    Outcome,
    ReleaseUserState,
    confirmation_run,
    fold_events,
    next_state,
    reopens_fail,
)

NOW = datetime(2026, 10, 8, 9, 30, tzinfo=UTC)


def _eval(at: datetime, any_fail: bool, all_pass: bool) -> VerdictEvaluation:
    return VerdictEvaluation(
        agent_id="a",
        release="r",
        evaluated_at=at,
        manual=False,
        seed="abcd1234",
        baseline_release="b",
        baseline_mode="previous_release",
        baseline_unverified=False,
        window_start=at,
        window_end=at,
        n_candidate_turns=10,
        n_baseline_turns=10,
        n_candidate_sessions=2,
        n_baseline_sessions=2,
        n_excluded_mixed=0,
        n_excluded_untagged=0,
        n_excluded_late=0,
        state=VerdictState.INCONCLUSIVE,
        reason=ReasonCode.fail_candidate,
        final=False,
        metrics={"any_fail": any_fail, "all_pass": all_pass},
        slices={},
        duration_ms=1,
    )


def _user(**kwargs: object) -> ReleaseUserState:
    base = ReleaseUserState(None, frozenset())
    for key, value in kwargs.items():
        setattr(base, key, value)
    return base


def test_later_evaluation_does_not_block_confirmation() -> None:
    later = _eval(NOW + timedelta(hours=1), False, False)
    prev = [later, _eval(NOW - timedelta(minutes=15), True, False)]
    state, reason, _final = next_state(
        VerdictState.INCONCLUSIVE,
        ReasonCode.fail_candidate,
        prev,
        NOW,
        Outcome(True, False),
        None,
        VerdictSettings(),
    )
    assert (state, reason) == (VerdictState.FAIL, ReasonCode.confirmed)


def test_fail_confirms_after_gap() -> None:
    prev = [_eval(NOW - timedelta(minutes=15), True, False)]
    state, reason, final = next_state(
        VerdictState.INCONCLUSIVE,
        ReasonCode.fail_candidate,
        prev,
        NOW,
        Outcome(True, False),
        None,
        VerdictSettings(),
    )
    assert (state, reason, final) == (VerdictState.FAIL, ReasonCode.confirmed, False)


def test_fail_stays_candidate_inside_gap() -> None:
    prev = [_eval(NOW - timedelta(minutes=5), True, False)]
    state, reason, _final = next_state(
        VerdictState.INCONCLUSIVE,
        ReasonCode.fail_candidate,
        prev,
        NOW,
        Outcome(True, False),
        None,
        VerdictSettings(),
    )
    assert (state, reason) == (VerdictState.INCONCLUSIVE, ReasonCode.fail_candidate)


def test_pass_confirms_after_gap() -> None:
    prev = [_eval(NOW - timedelta(minutes=15), False, True)]
    state, reason, _final = next_state(
        VerdictState.INCONCLUSIVE,
        ReasonCode.pass_candidate,
        prev,
        NOW,
        Outcome(False, True),
        None,
        VerdictSettings(),
    )
    assert (state, reason) == (VerdictState.PASS, ReasonCode.confirmed)


def test_pass_stays_pass_on_insufficient_power() -> None:
    state, reason, _final = next_state(
        VerdictState.PASS,
        ReasonCode.confirmed,
        [],
        NOW,
        Outcome(False, False),
        None,
        VerdictSettings(),
    )
    assert (state, reason) == (VerdictState.PASS, ReasonCode.confirmed)


def test_pass_can_become_fail_candidate() -> None:
    state, reason, _final = next_state(
        VerdictState.PASS,
        ReasonCode.confirmed,
        [],
        NOW,
        Outcome(True, False),
        None,
        VerdictSettings(),
    )
    assert (state, reason) == (VerdictState.INCONCLUSIVE, ReasonCode.fail_candidate)


def test_fail_stays_fail_on_all_pass() -> None:
    state, reason, final = next_state(
        VerdictState.FAIL,
        ReasonCode.confirmed,
        [],
        NOW,
        Outcome(False, True),
        None,
        VerdictSettings(),
    )
    assert (state, reason, final) == (VerdictState.FAIL, ReasonCode.confirmed, False)


def test_reopened_fail_restarts_confirmation() -> None:
    state, reason, final = next_state(
        VerdictState.FAIL,
        ReasonCode.confirmed,
        [],
        NOW,
        Outcome(False, True),
        None,
        VerdictSettings(),
        reopen=True,
    )
    assert (state, reason, final) == (VerdictState.INCONCLUSIVE, ReasonCode.pass_candidate, False)


def test_reopened_fail_on_a_final_check_confirms_directly() -> None:
    state, reason, final = next_state(
        VerdictState.FAIL,
        ReasonCode.confirmed,
        [],
        NOW,
        Outcome(False, True),
        ReasonCode.window_elapsed,
        VerdictSettings(),
        reopen=True,
    )
    assert (state, reason, final) == (VerdictState.PASS, ReasonCode.confirmed, True)


def test_reopens_fail_only_after_a_later_change() -> None:
    changed = _user(changed_at=NOW)
    assert reopens_fail(VerdictState.FAIL, NOW - timedelta(minutes=1), changed)
    assert reopens_fail(VerdictState.FAIL, None, changed)
    assert not reopens_fail(VerdictState.FAIL, NOW + timedelta(minutes=1), changed)
    assert not reopens_fail(VerdictState.FAIL, NOW - timedelta(minutes=1), _user())
    assert not reopens_fail(VerdictState.INCONCLUSIVE, NOW - timedelta(minutes=1), changed)


def test_confirmation_run_starts_after_the_last_change() -> None:
    prev = [
        _eval(NOW - timedelta(minutes=5), True, False),
        _eval(NOW - timedelta(minutes=20), True, False),
    ]
    assert confirmation_run(prev, "b", _user()) == prev
    assert confirmation_run(prev, "b", _user(changed_at=NOW - timedelta(minutes=10))) == prev[:1]
    assert confirmation_run(prev, "other", _user()) == []


@pytest.mark.parametrize("prev", [VerdictState.PENDING, VerdictState.INCONCLUSIVE])
@pytest.mark.parametrize(
    "ended", [ReasonCode.window_elapsed, ReasonCode.superseded, ReasonCode.stopped]
)
def test_monitoring_end_is_final_inconclusive(prev: VerdictState, ended: ReasonCode) -> None:
    state, reason, final = next_state(
        prev,
        ReasonCode.no_baseline,
        [],
        NOW,
        None,
        ended,
        VerdictSettings(),
        direct=(prev, ReasonCode.no_baseline),
    )
    assert (state, reason, final) == (VerdictState.INCONCLUSIVE, ended, True)


def test_final_check_confirms_without_the_gap() -> None:
    def ended(reason: ReasonCode, outcome: Outcome) -> tuple[VerdictState, ReasonCode, bool]:
        return next_state(
            VerdictState.INCONCLUSIVE,
            reason,
            [],
            NOW,
            outcome,
            ReasonCode.superseded,
            VerdictSettings(),
        )

    fail = ended(ReasonCode.fail_candidate, Outcome(True, False))
    assert fail == (VerdictState.FAIL, ReasonCode.confirmed, True)
    passed = ended(ReasonCode.pass_candidate, Outcome(False, True))
    assert passed == (VerdictState.PASS, ReasonCode.confirmed, True)
    calm = ended(ReasonCode.insufficient_power, Outcome(False, False))
    assert calm == (VerdictState.INCONCLUSIVE, ReasonCode.superseded, True)


def test_five_minute_cadence_confirms_on_streak_age() -> None:
    prev = [
        _eval(NOW - timedelta(minutes=5), True, False),
        _eval(NOW - timedelta(minutes=10), True, False),
        _eval(NOW - timedelta(minutes=15), False, False),
    ]
    vs = VerdictSettings(fail_confirmations=2)
    state, _reason, _final = next_state(
        VerdictState.INCONCLUSIVE,
        ReasonCode.fail_candidate,
        prev,
        NOW,
        Outcome(True, False),
        None,
        vs,
    )
    assert state is VerdictState.FAIL
    state, _reason, _final = next_state(
        VerdictState.INCONCLUSIVE,
        ReasonCode.fail_candidate,
        prev[:1],
        NOW,
        Outcome(True, False),
        None,
        vs,
    )
    assert state is VerdictState.INCONCLUSIVE


def test_pass_stays_pass_when_final() -> None:
    state, reason, final = next_state(
        VerdictState.PASS,
        ReasonCode.confirmed,
        [],
        NOW,
        Outcome(False, True),
        ReasonCode.window_elapsed,
        VerdictSettings(),
    )
    assert (state, reason, final) == (VerdictState.PASS, ReasonCode.confirmed, True)


def test_k1_confirms_immediately() -> None:
    settings = VerdictSettings(fail_confirmations=1)
    state, reason, _final = next_state(
        VerdictState.PENDING,
        ReasonCode.insufficient_sample,
        [],
        NOW,
        Outcome(True, False),
        None,
        settings,
    )
    assert (state, reason) == (VerdictState.FAIL, ReasonCode.confirmed)


def test_fold_events_latest_wins() -> None:
    events = [
        ReleaseEvent("a", "r", NOW, ReleaseEventType.manual_baseline, {"release": "old"}, ""),
        ReleaseEvent(
            "a",
            "r",
            NOW + timedelta(minutes=1),
            ReleaseEventType.manual_baseline,
            {"release": "new"},
            "sam",
        ),
        ReleaseEvent(
            "a",
            "r",
            NOW,
            ReleaseEventType.expected_changes,
            {"metrics": [MetricId.loop_rate.value]},
            "",
        ),
        ReleaseEvent(
            "a",
            "r",
            NOW + timedelta(minutes=2),
            ReleaseEventType.expected_changes,
            {"metrics": [MetricId.tool_error_rate.value]},
            "",
        ),
        ReleaseEvent("a", "r", NOW + timedelta(minutes=3), ReleaseEventType.stop, {}, "sam"),
        ReleaseEvent("a", "r", NOW + timedelta(minutes=4), ReleaseEventType.stop, {}, "sam"),
    ]
    folded = fold_events(events)
    assert folded.manual_baseline == "new"
    assert folded.expected_changes == frozenset({MetricId.tool_error_rate})
    assert folded.changed_at == NOW + timedelta(minutes=2)
    assert folded.stopped_at == NOW + timedelta(minutes=3)
