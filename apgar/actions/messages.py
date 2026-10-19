from __future__ import annotations

from datetime import datetime
from typing import Any

from apgar.domain.enums import (
    NotificationEvent,
    ReasonCode,
    VerdictState,
)
from apgar.domain.models import Agent, Release
from apgar.domain.time import to_iso
from apgar.verdict.headline import (
    MINUS,
    format_count,
    format_pp,
    format_rate,
    format_rel,
)

__all__ = [
    "MINUS",
    "format_pp",
    "format_rate",
    "format_rel",
    "slack_message",
    "slack_text",
    "webhook_payload",
    "webhook_test_payload",
]

DOT = "\u00b7"


def _event_name(event: NotificationEvent | str) -> str:
    if isinstance(event, NotificationEvent):
        return event.value
    return event


def _sample(summary: dict[str, Any], key: str) -> int:
    sample = summary.get("sample")
    value = sample.get(key) if isinstance(sample, dict) else None
    return int(value) if isinstance(value, int | float) else 0


def _baseline(summary: dict[str, Any]) -> str | None:
    baseline = summary.get("baseline")
    release = baseline.get("release") if isinstance(baseline, dict) else None
    return str(release) if release else None


def _failed(summary: dict[str, Any]) -> list[dict[str, Any]]:
    failed = summary.get("failed_metrics")
    if not isinstance(failed, list):
        return []
    return [item for item in failed if isinstance(item, dict)]


def _headlines(summary: dict[str, Any]) -> str:
    return " ".join(str(item.get("headline", "")) for item in _failed(summary)).strip()


def _duration(release: Release, summary: dict[str, Any]) -> str:
    window = summary.get("window")
    end = window.get("end") if isinstance(window, dict) else None
    end = end or summary.get("evaluated_at")
    if not isinstance(end, str):
        return "n/a"
    minutes = max(0, int((datetime.fromisoformat(end) - release.first_seen).total_seconds() // 60))
    return f"{minutes} min" if minutes < 60 else f"{round(minutes / 60)} h"


def _regression_line(summary: dict[str, Any]) -> str:
    early = ""
    if summary.get("early"):
        early = f", early, {format_count(_sample(summary, 'candidate_turns'))} turns"
    return f"Regression{early}. {_headlines(summary)}".rstrip()


def _healthy_line(summary: dict[str, Any]) -> str:
    turns = format_count(_sample(summary, "candidate_turns"))
    line = f"Healthy. No regression in {turns} turns against {_baseline(summary) or 'n/a'}."
    detectable = summary.get("detectability")
    if isinstance(detectable, str):
        line = f"{line} {detectable}"
    return line


def _ended_how(release: Release, summary: dict[str, Any]) -> str:
    ended = summary.get("ended")
    reason = ended.get("reason") if isinstance(ended, dict) else summary.get("reason")
    by = ended.get("by") if isinstance(ended, dict) else None
    duration = _duration(release, summary)
    if reason == ReasonCode.superseded.value:
        return f"{by or 'A newer release'} took over after {duration}."
    if reason == ReasonCode.stopped.value:
        return f"Stopped after {duration}."
    return f"Ended after {duration}."


def _ended_line(release: Release, summary: dict[str, Any]) -> str:
    turns = format_count(_sample(summary, "candidate_turns"))
    return (
        f"Unconfirmed. {_ended_how(release, summary)} No regression in {turns} turns, "
        "but not enough data to confirm it healthy."
    )


def slack_text(
    event: NotificationEvent | str,
    agent: Agent,
    release: Release,
    summary: dict[str, Any],
) -> str:
    kind = NotificationEvent(event)
    report = str(summary.get("report_url") or "")
    baseline = _baseline(summary)
    lines = [f"Apgar {DOT} {agent.name} {DOT} release {release.release}"]
    if kind == NotificationEvent.release_detected.value:
        compared = f"Comparing with {baseline}." if baseline else "Nothing to compare yet."
        lines.append(f"New release detected. {compared}")
        lines.append(f"Monitoring: {report}")
    elif kind == NotificationEvent.regression.value:
        lines.append(_regression_line(summary))
        n_c = format_count(_sample(summary, "candidate_turns"))
        n_b = format_count(_sample(summary, "baseline_turns"))
        lines.append(
            f"Based on {n_c} turns against {n_b} from {baseline or 'n/a'}. "
            f"Details and actions: {report}"
        )
    elif kind == NotificationEvent.healthy.value:
        lines.append(_healthy_line(summary))
    else:
        lines.append(_ended_line(release, summary))
    return "\n".join(lines)


_SLACK_COLORS = {
    "fail": "#B4262C",
    "pass": "#16774B",
    "inconclusive": "#8F4C00",
    "info": "#1D5EA8",
    "muted": "#6B6379",
}


def _mrkdwn(value: object) -> str:
    return str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _code(value: object) -> str:
    return f"`{_mrkdwn(value)}`"


def _section(text: str) -> dict[str, Any]:
    return {"type": "section", "text": {"type": "mrkdwn", "text": text}}


def _context(text: str) -> dict[str, Any]:
    return {"type": "context", "elements": [{"type": "mrkdwn", "text": text}]}


def _bullets(summary: dict[str, Any]) -> str:
    headlines = [str(item.get("headline") or "") for item in _failed(summary)]
    return "\n".join(f"• {_mrkdwn(line)}" for line in headlines if line)


def _baseline_unverified(summary: dict[str, Any]) -> bool:
    baseline = summary.get("baseline")
    return isinstance(baseline, dict) and bool(baseline.get("unverified"))


def _slack_card(
    kind: NotificationEvent, release: Release, summary: dict[str, Any]
) -> tuple[str, str, list[dict[str, Any]], str]:
    baseline = _baseline(summary)
    against = _code(baseline or "n/a")
    turns = format_count(_sample(summary, "candidate_turns"))
    if kind == NotificationEvent.release_detected.value:
        if baseline is None:
            return (
                "New release",
                "info",
                [_section("First release. Nothing to compare yet.")],
                "Watch the release",
            )
        blocks = [_section(f"Comparing with {against}.")]
        if _baseline_unverified(summary):
            blocks.append(_context(f"{against} was not itself confirmed healthy."))
        return "New release", "info", blocks, "Watch the release"
    if kind == NotificationEvent.regression.value:
        title = "Regression, early" if summary.get("early") else "Regression"
        base_turns = format_count(_sample(summary, "baseline_turns"))
        blocks = [
            _section(_bullets(summary) or "A guardrail metric is outside its tolerance."),
            _context(f"Based on {turns} turns against {base_turns} from {against}."),
        ]
        return title, "fail", blocks, "Details and actions"
    if kind == NotificationEvent.healthy.value:
        blocks = [_section(f"No regression in {turns} turns against {against}.")]
        detectable = summary.get("detectability")
        if isinstance(detectable, str) and detectable:
            blocks.append(_context(_mrkdwn(detectable)))
        return "Healthy", "pass", blocks, "Open the report"
    how = _mrkdwn(_ended_how(release, summary))
    body = f"{how} No regression in {turns} turns, but not enough data to confirm it healthy."
    return "Unconfirmed", "inconclusive", [_section(body)], "Open the report"


def slack_message(
    event: NotificationEvent | str,
    agent: Agent,
    release: Release,
    summary: dict[str, Any],
) -> dict[str, Any]:
    kind = NotificationEvent(event)
    title, tone, blocks, link = _slack_card(kind, release, summary)
    report = summary.get("report_url")
    if report:
        blocks.append(_section(f"<{report}|{link}>"))
    heading = f"*{title}* {DOT} {_mrkdwn(agent.name)} {DOT} release {_code(release.release)}"
    return {
        "text": slack_text(event, agent, release, summary),
        "blocks": [_section(heading)],
        "attachments": [{"color": _SLACK_COLORS[tone], "blocks": blocks}],
    }


_WEBHOOK_OMITTED = frozenset({"agent", "release", "ok", "excluded"})


def webhook_payload(
    event: NotificationEvent | str,
    agent: Agent,
    release: Release,
    summary: dict[str, Any],
    text: str,
    now: datetime,
    demo: bool,
    *,
    idempotency_key: str,
    previous_verdict: VerdictState | None,
) -> dict[str, Any]:
    return {
        "event": _event_name(event),
        "idempotency_key": idempotency_key,
        "agent": agent.name,
        "release": release.release,
        "demo": demo,
        "previous_verdict": None if previous_verdict is None else previous_verdict.value,
        "verdict": {key: value for key, value in summary.items() if key not in _WEBHOOK_OMITTED},
        "text": text,
        "sent_at": to_iso(now),
    }


def webhook_test_payload(now: datetime) -> dict[str, Any]:
    return {
        "event": "test",
        "idempotency_key": f"test:{to_iso(now)}",
        "agent": None,
        "release": None,
        "demo": False,
        "previous_verdict": None,
        "verdict": None,
        "text": "Apgar connection test",
        "sent_at": to_iso(now),
    }
