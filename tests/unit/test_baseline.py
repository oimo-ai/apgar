from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

from apgar.domain.enums import ReasonCode, VerdictState
from apgar.domain.models import Release
from apgar.storage.types import ReleaseActivity
from apgar.verdict.baseline import ended_clean, select_baseline
from apgar.verdict.state_machine import ReleaseUserState
from tests.factories import make_release

NOW = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)
LATER = NOW + timedelta(hours=6)


def _user(baseline: str | None = None) -> ReleaseUserState:
    return ReleaseUserState(baseline, frozenset())


def _release(
    name: str,
    days_ago: float,
    state: VerdictState = VerdictState.PENDING,
    reason: ReasonCode = ReasonCode.insufficient_sample,
    final: bool = False,
) -> Release:
    seen = NOW - timedelta(days=days_ago)
    return make_release(
        seen, release=name, first_seen=seen, state=state, reason=reason, final=final
    )


def _ended(name: str, days_ago: float, failing: bool = False) -> Release:
    row = _release(name, days_ago, VerdictState.INCONCLUSIVE, ReasonCode.window_elapsed, True)
    return replace(row, verdict_summary={"failed_metrics": [{"id": "x"}] if failing else []})


def _activity(**last_seen_hours_ago: float) -> dict[str, ReleaseActivity]:
    return {
        name: ReleaseActivity(name, NOW - timedelta(hours=hours), 10)
        for name, hours in last_seen_hours_ago.items()
    }


def test_no_prior_release_returns_none() -> None:
    candidate = _release("cand", 0)
    assert select_baseline(candidate, [candidate], _user(), {}, LATER) is None


def test_recency_decides_among_eligible_and_failed_are_skipped() -> None:
    passed = _release("pass", 5, VerdictState.PASS, ReasonCode.confirmed, True)
    ended = _ended("ended", 3)
    failed = _release("fail", 1, VerdictState.FAIL, ReasonCode.confirmed, True)
    candidate = _release("cand", 0)
    releases = [passed, ended, failed, candidate]
    choice = select_baseline(
        candidate, releases, _user(), _activity(**{"pass": 30, "ended": 20, "fail": 1}), LATER
    )
    assert choice is not None
    assert choice.release == "ended"
    assert choice.unverified is False
    assert choice.reported_mode == "previous_release"


def test_ended_in_fail_candidate_is_not_eligible() -> None:
    clean = _release("clean", 4, VerdictState.PASS, ReasonCode.confirmed, True)
    candidate_ended = _release(
        "possible", 1, VerdictState.INCONCLUSIVE, ReasonCode.fail_candidate, True
    )
    candidate = _release("cand", 0)
    choice = select_baseline(candidate, [clean, candidate_ended, candidate], _user(), {}, LATER)
    assert choice is not None and choice.release == "clean"
    unconfirmed = _ended("unconfirmed", 1, failing=True)
    choice = select_baseline(candidate, [clean, unconfirmed, candidate], _user(), {}, LATER)
    assert choice is not None and choice.release == "clean"


def test_unverified_when_every_prior_failed_or_still_running() -> None:
    failed = _release("fail", 2, VerdictState.FAIL, ReasonCode.confirmed, True)
    candidate = _release("cand", 0)
    choice = select_baseline(candidate, [failed, candidate], _user(), {}, LATER)
    assert choice is not None and choice.release == "fail" and choice.unverified

    running = _release("running", 1)
    choice = select_baseline(candidate, [failed, running, candidate], _user(), {}, LATER)
    assert choice is not None and choice.release == "running" and choice.unverified


def test_ended_clean_rules() -> None:
    assert ended_clean(_release("p", 1, VerdictState.PASS, ReasonCode.confirmed))
    assert ended_clean(_ended("e", 1))
    assert not ended_clean(_ended("e", 1, failing=True))
    assert not ended_clean(_release("r", 1, VerdictState.INCONCLUSIVE, ReasonCode.pass_candidate))


def test_hour_matching_is_applied_under_one_day() -> None:
    prior = _release("prior", 3, VerdictState.PASS, ReasonCode.confirmed, True)
    candidate = _release("cand", 0)
    activity = _activity(prior=1)
    releases = [prior, candidate]
    short = select_baseline(candidate, releases, _user(), activity, NOW + timedelta(hours=2))
    wide = select_baseline(candidate, releases, _user(), activity, NOW + timedelta(hours=30))
    assert short is not None
    assert short.hour_of_day_filter == frozenset({12, 13})
    assert short.window_start == NOW - timedelta(days=7)
    assert short.window_end == NOW
    assert wide is not None and wide.hour_of_day_filter is None


def test_hour_matching_needs_a_baseline_that_ran_a_day_in_the_window() -> None:
    candidate = _release("cand", 0)
    when = NOW + timedelta(hours=2)
    cases: list[tuple[float, dict[str, float], frozenset[int] | None]] = [
        (1 / 24, {"prior": 0}, None),
        (1, {"prior": 0}, frozenset({12, 13})),
        (1, {"prior": 1 / 60}, None),
        (2 / 24, {"prior": -5}, None),
        (10, {"prior": 6.5 * 24}, None),
        (10, {"prior": 5 * 24}, frozenset({12, 13})),
        (3, {}, None),
    ]
    for days_ago, last_seen_hours_ago, expected in cases:
        prior = _release("prior", days_ago, VerdictState.PASS, ReasonCode.confirmed, True)
        activity = _activity(**last_seen_hours_ago)
        for user in (_user(), _user("prior")):
            choice = select_baseline(candidate, [prior, candidate], user, activity, when)
            assert choice is not None and choice.release == "prior"
            assert choice.hour_of_day_filter == expected, (days_ago, last_seen_hours_ago)


def test_manual_baseline_uses_the_previous_release_window() -> None:
    named = _release("named", 1, VerdictState.FAIL, ReasonCode.confirmed)
    candidate = _release("cand", 0)
    newer = _release("newer", -1)
    releases = [named, candidate, newer]
    manual = select_baseline(candidate, releases, _user("named"), {}, LATER)
    missing = select_baseline(candidate, releases, _user("gone"), {}, LATER)
    later = select_baseline(candidate, releases, _user("newer"), {}, LATER)
    assert manual is not None and manual.manual and manual.unverified
    assert manual.reported_mode == "manual"
    assert manual.window_start == NOW - timedelta(days=7) and manual.window_end == NOW
    for fallback in (missing, later):
        assert fallback is not None and not fallback.manual and fallback.release == "named"
