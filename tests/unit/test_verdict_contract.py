from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from apgar.domain.enums import ReasonCode, VerdictState
from apgar.verdict.summary import build_summary, pending_summary
from tests.factories import make_agent, make_evaluation, make_release

NOW = datetime(2026, 10, 8, 9, 30, tzinfo=UTC)


class _Slice(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dimension: str
    value: str


class _Failed(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    baseline: float | None
    candidate: float | None
    delta: float | None
    ci: list[float] | None
    tolerance: float
    tolerance_mode: str | None
    direction: str | None
    unit: str | None
    worst_slice: _Slice | None = None
    headline: str


class _Baseline(BaseModel):
    model_config = ConfigDict(extra="forbid")

    release: str | None
    mode: str | None
    unverified: bool


class _Sample(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_turns: int
    baseline_turns: int
    candidate_sessions: int
    baseline_sessions: int


class _Excluded(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mixed: int
    untagged: int
    late: int


class _Window(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start: str | None
    end: str | None
    max_end: str | None


class _Ended(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: ReasonCode
    by: str | None


class VerdictContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent: str
    release: str
    verdict: VerdictState
    reason: ReasonCode
    final: bool
    ok: bool | None
    baseline: _Baseline
    sample: _Sample
    excluded: _Excluded
    window: _Window
    evaluated_at: str | None
    early: bool
    ended: _Ended | None
    detectability: str | None
    failed_metrics: list[_Failed]
    report_url: str


def expression_holds(result: dict[str, Any], expression: str) -> bool:
    left, right = (part.strip() for part in expression.split("=="))
    key = left.removeprefix("result.")
    return str(result[key]) == right.strip("'\"")


def _evaluation(state: VerdictState) -> object:
    status = "FAIL" if state is VerdictState.FAIL else "PASS"
    return make_evaluation(
        NOW,
        state=state,
        n_candidate_turns=20,
        n_baseline_turns=18,
        window_start=NOW,
        window_end=NOW,
        metrics={
            "items": {
                "tool_error_rate": {
                    "role": "guardrail",
                    "status": status,
                    "direction": "up",
                    "baseline": 0.01,
                    "candidate": 0.08,
                    "delta": 0.07,
                    "ci": [0.02, 0.09],
                    "tolerance": 0.02,
                }
            }
        },
        slices={
            "tool_error_rate": {
                "tool": {"values": [{"value": "sql_query", "status": status, "delta": 0.07}]}
            }
        },
    )


def test_verdict_contract(settings: object) -> None:
    from apgar.config import Settings

    assert isinstance(settings, Settings)
    settings = settings.model_copy(update={"public_url": "https://apgar.acme.dev"})
    agent = make_agent(NOW, name="billing-copilot")
    summaries: dict[str, dict[str, Any]] = {}
    for state in (VerdictState.PASS, VerdictState.FAIL, VerdictState.INCONCLUSIVE):
        reason = ReasonCode.confirmed
        if state is VerdictState.INCONCLUSIVE:
            reason = ReasonCode.insufficient_power
        release = make_release(
            NOW,
            agent_id=agent.id,
            release="a1b2c3d",
            state=state,
            reason=reason,
            selected_baseline_release="9f8e7d6",
            selected_baseline_mode="previous_release",
            first_seen=NOW,
        )
        summaries[state.value] = build_summary(agent, release, _evaluation(state), settings)  # type: ignore[arg-type]
    pending_release = make_release(
        NOW,
        agent_id=agent.id,
        release="a1b2c3d",
        state=VerdictState.PENDING,
        reason=ReasonCode.no_baseline,
        first_seen=NOW,
    )
    summaries["PENDING"] = pending_summary(agent, pending_release, settings)
    ok = {"PASS": True, "FAIL": False, "PENDING": None, "INCONCLUSIVE": None}
    for verdict, summary in summaries.items():
        parsed = VerdictContract.model_validate(summary)
        assert parsed.ok is ok[verdict]
        assert parsed.reason is not None
        assert summary["report_url"].startswith("https://")
        for item in summary["failed_metrics"]:
            for key in ("id", "baseline", "candidate", "delta", "ci", "tolerance"):
                assert key in item
    assert expression_holds(summaries["PASS"], "result.verdict == 'PASS'")
    assert not expression_holds(summaries["PASS"], "result.verdict == 'FAIL'")
    assert expression_holds(summaries["FAIL"], "result.verdict == 'FAIL'")
    assert not expression_holds(summaries["FAIL"], "result.verdict == 'PASS'")
    for verdict in ("PENDING", "INCONCLUSIVE"):
        assert not expression_holds(summaries[verdict], "result.verdict == 'PASS'")
        assert not expression_holds(summaries[verdict], "result.verdict == 'FAIL'")
    assert summaries["FAIL"]["failed_metrics"]
    assert summaries["PASS"]["failed_metrics"] == []
