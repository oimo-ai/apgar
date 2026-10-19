from __future__ import annotations

from datetime import UTC, datetime

from apgar.api.present import release_out
from apgar.domain.enums import ReasonCode, VerdictState
from tests.factories import make_agent, make_release

NOW = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)


def test_release_out_carries_early_flag_and_failing_metrics() -> None:
    release = make_release(
        NOW,
        first_seen=NOW,
        state=VerdictState.INCONCLUSIVE,
        reason=ReasonCode.fail_candidate,
        verdict_summary={
            "early": True,
            "failed_metrics": [
                {"id": "tool_error_rate", "headline": "Tool error rate rose."},
                "malformed",
            ],
        },
    )
    body = release_out(make_agent(NOW), release)
    assert body["early"] is True
    assert body["failing_metrics"] == [
        {"id": "tool_error_rate", "headline": "Tool error rate rose."}
    ]


def test_release_out_defaults_without_verdict_summary() -> None:
    body = release_out(make_agent(NOW), make_release(NOW, first_seen=NOW, verdict_summary={}))
    assert body["early"] is False
    assert body["failing_metrics"] == []
