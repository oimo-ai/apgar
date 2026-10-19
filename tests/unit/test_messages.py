from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from apgar.actions.messages import (
    slack_message,
    slack_text,
)
from tests.factories import make_agent, make_release

NOW = datetime(2026, 10, 8, 9, 30, tzinfo=UTC)
REPORT = "https://apgar.acme.dev/agents/billing-copilot/releases/v1.9.0"
HEADLINE = (
    "Tool error rate rose from 2.6% to 27.1% (allowed: up to +2 pp). "
    "Concentrated in web_search and fetch_url."
)
HEADER = "Apgar · billing-copilot · release v1.9.0"
AGENT = make_agent(NOW)
RELEASE = make_release(NOW - timedelta(hours=9), release="v1.9.0")


def _summary(**overrides: Any) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "verdict": "FAIL",
        "reason": "confirmed",
        "final": False,
        "early": False,
        "ended": None,
        "detectability": None,
        "baseline": {"release": "v1.8.0", "mode": "previous_release", "unverified": False},
        "sample": {"candidate_turns": 80, "baseline_turns": 40},
        "evaluated_at": "2026-10-08T09:30:00.000Z",
        "failed_metrics": [
            {"id": "tool_error_rate", "delta": 0.245, "tolerance_mode": "abs", "headline": HEADLINE}
        ],
        "report_url": REPORT,
    }
    summary.update(overrides)
    return summary


def test_release_detected_names_baseline() -> None:
    text = slack_text("release_detected", AGENT, RELEASE, _summary(failed_metrics=[]))
    assert text == (f"{HEADER}\nNew release detected. Comparing with v1.8.0.\nMonitoring: {REPORT}")
    first = _summary(baseline={"release": None, "mode": None, "unverified": False})
    assert "Nothing to compare yet." in slack_text("release_detected", AGENT, RELEASE, first)


def test_regression_message() -> None:
    assert slack_text("regression", AGENT, RELEASE, _summary()) == (
        f"{HEADER}\nRegression. {HEADLINE}\n"
        f"Based on 80 turns against 40 from v1.8.0. Details and actions: {REPORT}"
    )
    early = slack_text("regression", AGENT, RELEASE, _summary(early=True))
    assert early.splitlines()[1].startswith("Regression, early, 80 turns. Tool error rate")


def test_healthy() -> None:
    detectable = "Smallest detectable change in tool error rate: +2.9 pp."
    healthy = _summary(
        verdict="PASS",
        failed_metrics=[],
        sample={"candidate_turns": 2310},
        detectability=detectable,
    )
    assert slack_text("healthy", AGENT, RELEASE, healthy) == (
        f"{HEADER}\nHealthy. No regression in 2,310 turns against v1.8.0. {detectable}"
    )


def test_ended_messages() -> None:
    superseded = _summary(
        verdict="INCONCLUSIVE",
        reason="superseded",
        final=True,
        failed_metrics=[],
        sample={"candidate_turns": 1420},
        ended={"reason": "superseded", "by": "v1.10.0"},
    )
    assert slack_text("ended", AGENT, RELEASE, superseded).splitlines()[1] == (
        "Unconfirmed. v1.10.0 took over after 9 h. No regression in 1,420 turns, "
        "but not enough data to confirm it healthy."
    )
    elapsed = {**superseded, "reason": "window_elapsed", "ended": None}
    elapsed["sample"] = {"candidate_turns": 1120}
    assert slack_text("ended", AGENT, RELEASE, elapsed).splitlines()[1] == (
        "Unconfirmed. Ended after 9 h. No regression in 1,120 turns, "
        "but not enough data to confirm it healthy."
    )
    late = make_release(NOW - timedelta(hours=80), release="v1.9.0")
    capped = {**elapsed, "window": {"end": "2026-10-08T01:30:00.000Z"}}
    assert "Ended after 72 h." in slack_text("ended", AGENT, late, capped)
    short = make_release(NOW - timedelta(minutes=45), release="v1.9.0")
    assert "after 45 min" in slack_text("ended", AGENT, short, elapsed)
    stopped = {**elapsed, "ended": {"reason": "stopped", "by": None}}
    assert (
        slack_text("ended", AGENT, RELEASE, stopped)
        .splitlines()[1]
        .startswith("Unconfirmed. Stopped after 9 h. No regression in 1,120 turns")
    )


def _card(message: dict[str, Any]) -> tuple[str, str, list[str]]:
    heading = message["blocks"][0]["text"]["text"]
    attachment = message["attachments"][0]
    lines = [
        block["text"]["text"] if block["type"] == "section" else block["elements"][0]["text"]
        for block in attachment["blocks"]
    ]
    return heading, attachment["color"], lines


def test_slack_message_events() -> None:
    regression = slack_message("regression", AGENT, RELEASE, _summary())
    assert regression["text"] == slack_text("regression", AGENT, RELEASE, _summary())
    assert _card(regression) == (
        "*Regression* · billing-copilot · release `v1.9.0`",
        "#B4262C",
        [
            f"• {HEADLINE}",
            "Based on 80 turns against 40 from `v1.8.0`.",
            f"<{REPORT}|Details and actions>",
        ],
    )
    early = slack_message("regression", AGENT, RELEASE, _summary(early=True))
    assert _card(early)[0].startswith("*Regression, early* ·")

    detected = slack_message("release_detected", AGENT, RELEASE, _summary(failed_metrics=[]))
    assert _card(detected) == (
        "*New release* · billing-copilot · release `v1.9.0`",
        "#1D5EA8",
        ["Comparing with `v1.8.0`.", f"<{REPORT}|Watch the release>"],
    )
    unverified = _summary(baseline={"release": "v1.8.0", "mode": "manual", "unverified": True})
    assert _card(slack_message("release_detected", AGENT, RELEASE, unverified))[2][1] == (
        "`v1.8.0` was not itself confirmed healthy."
    )
    first = _summary(baseline={"release": None, "mode": None, "unverified": False})
    assert _card(slack_message("release_detected", AGENT, RELEASE, first))[2][0] == (
        "First release. Nothing to compare yet."
    )

    detectable = "Smallest detectable change in tool error rate: +2.9 pp."
    healthy = _summary(
        verdict="PASS",
        failed_metrics=[],
        sample={"candidate_turns": 2310},
        detectability=detectable,
    )
    assert _card(slack_message("healthy", AGENT, RELEASE, healthy)) == (
        "*Healthy* · billing-copilot · release `v1.9.0`",
        "#16774B",
        [
            "No regression in 2,310 turns against `v1.8.0`.",
            detectable,
            f"<{REPORT}|Open the report>",
        ],
    )

    stopped = _summary(
        verdict="INCONCLUSIVE",
        reason="stopped",
        final=True,
        failed_metrics=[],
        sample={"candidate_turns": 1120},
        ended={"reason": "stopped", "by": None},
    )
    heading, color, lines = _card(slack_message("ended", AGENT, RELEASE, stopped))
    assert heading.startswith("*Unconfirmed* ·")
    assert color == "#8F4C00"
    assert lines[0] == (
        "Stopped after 9 h. No regression in 1,120 turns, "
        "but not enough data to confirm it healthy."
    )


def test_slack_message_escapes_mrkdwn() -> None:
    risky = _summary(failed_metrics=[{"id": "tool_error_rate", "headline": "a <b> & c"}])
    assert _card(slack_message("regression", AGENT, RELEASE, risky))[2][0] == (
        "• a &lt;b&gt; &amp; c"
    )
