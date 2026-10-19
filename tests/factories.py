from __future__ import annotations

from datetime import datetime

from apgar.domain.enums import (
    ConnectionStatus,
    ConnectionType,
    JobRequestKind,
    NotificationChannel,
    NotificationEvent,
    NotificationStatus,
    OutputFormat,
    ReasonCode,
    ReleaseEventType,
    Source,
    VerdictState,
)
from apgar.domain.models import (
    Agent,
    Connection,
    IngestToken,
    JobRequest,
    Notification,
    Release,
    ReleaseEvent,
    SyncState,
    VerdictEvaluation,
)
from apgar.domain.settings import (
    AgentFilter,
    ReleaseSettings,
    SurfaceMapping,
    VerdictSettings,
)


def make_agent(now: datetime, **overrides: object) -> Agent:
    agent = Agent(
        id="00000000-0000-4000-8000-000000000001",
        name="billing-copilot",
        source=Source.otlp,
        langfuse_connection_id="",
        filter=AgentFilter(trace_name="billing", tags=["prod"], metadata={"team": "rev"}),
        environment="",
        surface_mapping=SurfaceMapping(from_attribute="metadata.channel"),
        release_settings=ReleaseSettings(from_attribute="service.version"),
        metric_settings={"tool_error_rate": {"tolerance": 0.05}},
        verdict_settings=VerdictSettings(),
        output_format=OutputFormat.text,
        slack_connection_id="",
        is_demo=False,
        created_at=now,
        updated_at=now,
        deleted_at=None,
    )
    for key, value in overrides.items():
        setattr(agent, key, value)
    return agent


def make_connection(now: datetime, **overrides: object) -> Connection:
    connection = Connection(
        id="00000000-0000-4000-8000-0000000000c1",
        name="langfuse-prod",
        type=ConnectionType.langfuse,
        config={"host": "https://cloud.langfuse.com", "public_key": "pk"},
        status=ConnectionStatus.untested,
        last_checked_at=None,
        last_error="",
        created_at=now,
        updated_at=now,
    )
    for key, value in overrides.items():
        setattr(connection, key, value)
    return connection


def make_ingest_token(now: datetime, **overrides: object) -> IngestToken:
    token = IngestToken(
        id="00000000-0000-4000-8000-0000000000i1",
        name="default",
        token_hash="abc",
        token_prefix="apg_ing_abcd",
        agent_id="",
        auto_create_agents=True,
        created_at=now,
        revoked_at=None,
        updated_at=now,
    )
    for key, value in overrides.items():
        setattr(token, key, value)
    return token


def make_sync_state(now: datetime, **overrides: object) -> SyncState:
    state = SyncState(
        connection_id="00000000-0000-4000-8000-0000000000c1",
        watermark=None,
        last_success_at=None,
        last_error="",
        last_error_at=None,
        lag_seconds=None,
        in_progress=False,
        updated_at=now,
    )
    for key, value in overrides.items():
        setattr(state, key, value)
    return state


def make_release(now: datetime, **overrides: object) -> Release:
    release = Release(
        agent_id="00000000-0000-4000-8000-000000000001",
        release="a1b2c3d",
        first_seen=now,
        state=VerdictState.PENDING,
        reason=ReasonCode.no_baseline,
        final=False,
        final_at=None,
        selected_baseline_release="",
        selected_baseline_mode="",
        baseline_unverified=False,
        verdict_summary={},
        verdict_updated_at=None,
        last_seen=None,
        turn_count=0,
        updated_at=now,
    )
    for key, value in overrides.items():
        setattr(release, key, value)
    return release


def make_release_event(now: datetime, **overrides: object) -> ReleaseEvent:
    event = ReleaseEvent(
        agent_id="00000000-0000-4000-8000-000000000001",
        release="a1b2c3d",
        ts=now,
        type=ReleaseEventType.manual_baseline,
        payload={"release": "0a1b2c3"},
        actor="tester",
    )
    for key, value in overrides.items():
        setattr(event, key, value)
    return event


def make_evaluation(now: datetime, **overrides: object) -> VerdictEvaluation:
    evaluation = VerdictEvaluation(
        agent_id="00000000-0000-4000-8000-000000000001",
        release="a1b2c3d",
        evaluated_at=now,
        manual=False,
        seed="1",
        baseline_release="baseline",
        baseline_mode="previous_release",
        baseline_unverified=False,
        window_start=None,
        window_end=None,
        n_candidate_turns=10,
        n_baseline_turns=12,
        n_candidate_sessions=3,
        n_baseline_sessions=4,
        n_excluded_mixed=0,
        n_excluded_untagged=1,
        n_excluded_late=0,
        state=VerdictState.PENDING,
        reason=ReasonCode.insufficient_sample,
        final=False,
        metrics={"tool_error_rate": {"status": "NA"}},
        slices={},
        duration_ms=15,
    )
    for key, value in overrides.items():
        setattr(evaluation, key, value)
    return evaluation


def make_notification(now: datetime, **overrides: object) -> Notification:
    notification = Notification(
        id="00000000-0000-4000-8000-0000000000n1",
        agent_id="00000000-0000-4000-8000-000000000001",
        release="a1b2c3d",
        event=NotificationEvent.regression,
        idempotency_key="billing-copilot:a1b2c3d:PENDING->FAIL:2026-10-08T09:30:00.000Z",
        channel=NotificationChannel.slack,
        connection_id="00000000-0000-4000-8000-0000000000c1",
        status=NotificationStatus.pending,
        attempts=0,
        next_attempt_at=now,
        last_error="",
        payload={"text": "fail"},
        created_at=now,
        updated_at=now,
    )
    for key, value in overrides.items():
        setattr(notification, key, value)
    return notification


def make_job(now: datetime, **overrides: object) -> JobRequest:
    job = JobRequest(
        id="00000000-0000-4000-8000-0000000000j1",
        agent_id="00000000-0000-4000-8000-000000000001",
        release="a1b2c3d",
        kind=JobRequestKind.evaluate,
        payload={"manual": True},
        requested_at=now,
        processed_at=None,
        updated_at=now,
    )
    for key, value in overrides.items():
        setattr(job, key, value)
    return job
