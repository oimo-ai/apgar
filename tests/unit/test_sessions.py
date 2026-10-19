from __future__ import annotations

from datetime import datetime, timedelta

from apgar.domain.sessions import compute_session_fields
from tests.support import make_turn


def test_indexes_and_depth_buckets(fixed_now: datetime) -> None:
    turns = [
        make_turn(
            fixed_now,
            turn_id=f"t{index}",
            session_id="s",
            start_ts=fixed_now + timedelta(minutes=index),
            end_ts=fixed_now + timedelta(minutes=index, seconds=30),
        )
        for index in range(21)
    ]
    fields = compute_session_fields(turns, fixed_now + timedelta(hours=2))
    assert fields["t4"].turn_index == 5
    assert fields["t4"].depth_bucket == "short"
    assert fields["t5"].turn_index == 6
    assert fields["t5"].depth_bucket == "medium"
    assert fields["t19"].turn_index == 20
    assert fields["t19"].depth_bucket == "medium"
    assert fields["t20"].turn_index == 21
    assert fields["t20"].depth_bucket == "long"


def test_mixed_detection(fixed_now: datetime) -> None:
    turns = [
        make_turn(fixed_now, turn_id="a", session_id="s", release="r1", start_ts=fixed_now),
        make_turn(
            fixed_now,
            turn_id="b",
            session_id="s",
            release="r1",
            start_ts=fixed_now + timedelta(minutes=1),
        ),
        make_turn(
            fixed_now,
            turn_id="c",
            session_id="s",
            release="r2",
            start_ts=fixed_now + timedelta(minutes=2),
        ),
    ]
    fields = compute_session_fields(turns, fixed_now + timedelta(hours=2))
    assert fields["a"].mixed_session is False
    assert fields["b"].mixed_session is False
    assert fields["c"].mixed_session is True


def test_session_closed_after_quiet_window(fixed_now: datetime) -> None:
    now = fixed_now + timedelta(hours=2)
    closed = make_turn(
        fixed_now,
        turn_id="g",
        session_id="closed",
        start_ts=fixed_now,
        end_ts=fixed_now + timedelta(seconds=10),
    )
    open_turn = make_turn(
        fixed_now,
        turn_id="h",
        session_id="open",
        start_ts=now - timedelta(minutes=1),
        end_ts=now - timedelta(seconds=30),
    )
    fields = compute_session_fields([closed, open_turn], now)
    assert fields["g"].session_closed is True
    assert fields["h"].session_closed is False
