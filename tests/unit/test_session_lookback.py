from __future__ import annotations

from datetime import datetime, timedelta

from apgar.domain.models import TurnRow
from apgar.domain.retention import SESSION_LOOKBACK_DAYS
from apgar.storage.memory import InMemoryEventStore
from apgar.storage.types import ArmQuery, ArmTurn
from tests.support import make_turn


def _query(now: datetime) -> ArmQuery:
    return ArmQuery(
        agent_id="agent",
        release="v2",
        window_start=now,
        window_end=now + timedelta(hours=1),
        environment="",
        include_mixed=True,
        session_min_first_start=None,
        hour_of_day_filter=None,
        now=now + timedelta(hours=2),
        count_untagged=False,
    )


def _pair(now: datetime, session_id: str, earlier: datetime, suffix: str) -> list[TurnRow]:
    return [
        make_turn(
            now,
            turn_id=f"prior-{suffix}",
            release="v1",
            session_id=session_id,
            start_ts=earlier,
            end_ts=earlier,
            trace_id=f"{suffix}1" * 16,
        ),
        make_turn(
            now,
            turn_id=f"current-{suffix}",
            release="v2",
            session_id=session_id,
            start_ts=now,
            end_ts=now,
            trace_id=f"{suffix}2" * 16,
        ),
    ]


async def test_lookback_ignores_turns_older_than_the_window(fixed_now: datetime) -> None:
    event = InMemoryEventStore()
    outside = fixed_now - timedelta(days=SESSION_LOOKBACK_DAYS + 1)
    inside = fixed_now - timedelta(days=SESSION_LOOKBACK_DAYS - 1)
    edge = fixed_now - timedelta(days=SESSION_LOOKBACK_DAYS)
    await event.upsert_turns(
        [
            *_pair(fixed_now, "gap", outside, "a"),
            *_pair(fixed_now, "near", inside, "b"),
            *_pair(fixed_now, "edge", edge, "c"),
        ]
    )
    arm = await event.load_arm(_query(fixed_now))
    by_id = {turn.turn_id: turn for turn in arm.turns}

    assert _fields(by_id["current-a"]) == (1, False)
    assert _fields(by_id["current-b"]) == (2, True)
    assert _fields(by_id["current-c"]) == (2, True)


def _fields(turn: ArmTurn) -> tuple[int, bool]:
    return turn.turn_index, turn.mixed_session
