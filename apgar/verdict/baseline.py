from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from apgar.domain.enums import BaselineMode, ReasonCode, VerdictState
from apgar.domain.models import Release
from apgar.domain.settings import BASELINE_DAYS
from apgar.storage.types import ReleaseActivity
from apgar.verdict.state_machine import ReleaseUserState

ENDED_REASONS = frozenset({ReasonCode.superseded, ReasonCode.window_elapsed})


@dataclass(slots=True)
class BaselineChoice:
    release: str
    unverified: bool
    manual: bool
    window_start: datetime
    window_end: datetime
    hour_of_day_filter: frozenset[int] | None

    @property
    def reported_mode(self) -> str:
        mode = BaselineMode.manual if self.manual else BaselineMode.previous_release
        return mode.value


def hours_covered(start: datetime, end: datetime) -> frozenset[int]:
    if end <= start or end - start >= timedelta(hours=24):
        return frozenset()
    hours: set[int] = set()
    cursor = start
    while cursor < end:
        hours.add(cursor.hour)
        cursor = cursor.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    return frozenset(hours)


def failed(release: Release) -> bool:
    if release.state is VerdictState.FAIL or release.reason is ReasonCode.fail_candidate:
        return True
    return release.final and bool(release.verdict_summary.get("failed_metrics"))


def ended_clean(release: Release) -> bool:
    if release.state is VerdictState.PASS:
        return True
    return (
        release.final
        and release.state is VerdictState.INCONCLUSIVE
        and release.reason in ENDED_REASONS
        and not release.verdict_summary.get("failed_metrics")
    )


def _activity_key(
    activity: dict[str, ReleaseActivity], release: Release
) -> tuple[datetime, datetime]:
    seen = activity.get(release.release)
    last = None if seen is None else seen.last_seen
    return (last or release.first_seen, release.first_seen)


def _window(
    candidate: Release,
    window_end: datetime,
) -> tuple[datetime, datetime, frozenset[int] | None]:
    start = candidate.first_seen - timedelta(days=BASELINE_DAYS)
    end = candidate.first_seen
    covered = hours_covered(candidate.first_seen, window_end)
    return start, end, covered or None


def select_baseline(
    candidate: Release,
    releases: list[Release],
    user_state: ReleaseUserState,
    activity: dict[str, ReleaseActivity],
    window_end: datetime,
) -> BaselineChoice | None:
    prior = [
        release
        for release in releases
        if release.first_seen < candidate.first_seen
        and release.release != "untagged"
        and release.release != candidate.release
    ]
    pick: Release | None = None
    manual = False
    named = user_state.manual_baseline
    if named is not None:
        pick = next((release for release in prior if release.release == named), None)
        manual = pick is not None
    if pick is None:
        pool = [release for release in prior if not failed(release)] or prior
        if not pool:
            return None
        pick = max(pool, key=lambda release: _activity_key(activity, release))
    start, end, hours = _window(candidate, window_end)
    return BaselineChoice(
        release=pick.release,
        unverified=not ended_clean(pick),
        manual=manual,
        window_start=start,
        window_end=end,
        hour_of_day_filter=hours,
    )
