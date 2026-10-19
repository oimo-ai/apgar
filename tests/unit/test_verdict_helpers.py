from __future__ import annotations

from datetime import UTC, datetime, timedelta

from apgar.config import Settings
from apgar.domain.settings import MAX_WINDOW_HOURS, MIN_WINDOW_HOURS, VerdictSettings
from apgar.verdict.baseline import BaselineChoice
from apgar.verdict.headline import attribution
from apgar.worker.jobs.verdict import next_check_due

NOW = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)


def test_next_check_waits_for_traffic_and_never_passes_the_cap(settings: Settings) -> None:
    first_seen = NOW - timedelta(hours=10)
    cap = first_seen + timedelta(hours=72)
    idle = next_check_due(NOW - timedelta(days=2), NOW, first_seen, 72, settings, NOW)
    assert idle == cap
    assert next_check_due(NOW, None, first_seen, 72, settings, NOW) == NOW
    regular = next_check_due(NOW, NOW, first_seen, 72, settings, NOW)
    assert NOW < regular <= cap
    late = NOW - timedelta(hours=1)
    assert next_check_due(late, late, NOW - timedelta(hours=72), 72, settings, late) <= NOW


def test_attribution_distinguishes_no_signal_from_too_few_turns() -> None:
    clean = {"values": [{"value": "web", "status": "NOT_FLAGGED"}]}
    assert attribution({"surface": clean}, 500) == "No single slice stands out."
    assert attribution({}, 30) == "Attribution pending (30 turns)."


def test_stored_window_is_clamped() -> None:
    assert VerdictSettings.from_stored({"max_window_hours": 0}).max_window_hours == (
        MIN_WINDOW_HOURS
    )
    assert VerdictSettings.from_stored({"max_window_hours": 9999}).max_window_hours == (
        MAX_WINDOW_HOURS
    )


def test_manual_baseline_reports_manual_mode() -> None:
    def choice(manual: bool) -> BaselineChoice:
        return BaselineChoice("v1", False, manual, NOW, NOW, None)

    assert choice(True).reported_mode == "manual"
    assert choice(False).reported_mode == "previous_release"
