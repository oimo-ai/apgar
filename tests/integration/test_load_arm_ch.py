from __future__ import annotations

from datetime import timedelta

import pytest

from apgar.domain.retention import SESSION_LOOKBACK_DAYS
from apgar.storage.types import ArmQuery
from tests.support import FIXTURE_NOW, ChDatabase, make_turn

pytestmark = pytest.mark.integration


async def test_load_arm_excludes_late_and_mixed(ch_database: ChDatabase) -> None:
    _settings, event, _meta = ch_database
    now = FIXTURE_NOW
    rows = [
        make_turn(now, turn_id="clean", release="rel", session_id="solo", start_ts=now),
        make_turn(now, turn_id="late", release="rel", session_id="solo", start_ts=now, late=True),
        make_turn(now, turn_id="first", release="other", session_id="mix", start_ts=now),
        make_turn(
            now,
            turn_id="second",
            release="rel",
            session_id="mix",
            start_ts=now + timedelta(minutes=1),
        ),
    ]
    await event.upsert_turns(rows)
    arm = await event.load_arm(
        ArmQuery(
            agent_id=rows[0].agent_id,
            release="rel",
            window_start=now - timedelta(hours=1),
            window_end=now + timedelta(hours=1),
            environment="",
            include_mixed=False,
            session_min_first_start=None,
            hour_of_day_filter=None,
            now=now + timedelta(hours=2),
            count_untagged=False,
        )
    )
    assert arm.n_excluded_late == 1
    assert {turn.turn_id for turn in arm.turns} == {"clean"}
    assert arm.n_excluded_mixed == 1


async def test_session_lookback_ignores_turns_older_than_the_window(
    ch_database: ChDatabase,
) -> None:
    _settings, event, _meta = ch_database
    now = FIXTURE_NOW
    outside = now - timedelta(days=SESSION_LOOKBACK_DAYS + 1)
    inside = now - timedelta(days=SESSION_LOOKBACK_DAYS - 1)
    rows = [
        make_turn(
            now,
            turn_id="prior-gap",
            release="v1",
            session_id="gap",
            start_ts=outside,
            end_ts=outside,
            trace_id="a1" * 16,
        ),
        make_turn(
            now,
            turn_id="current-gap",
            release="v2",
            session_id="gap",
            start_ts=now,
            end_ts=now,
            trace_id="a2" * 16,
        ),
        make_turn(
            now,
            turn_id="prior-near",
            release="v1",
            session_id="near",
            start_ts=inside,
            end_ts=inside,
            trace_id="b1" * 16,
        ),
        make_turn(
            now,
            turn_id="current-near",
            release="v2",
            session_id="near",
            start_ts=now + timedelta(minutes=1),
            end_ts=now + timedelta(minutes=1),
            trace_id="b2" * 16,
        ),
    ]
    await event.upsert_turns(rows)
    arm = await event.load_arm(
        ArmQuery(
            agent_id=rows[0].agent_id,
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
    )
    by_id = {turn.turn_id: turn for turn in arm.turns}
    assert (by_id["current-gap"].turn_index, by_id["current-gap"].mixed_session) == (1, False)
    assert (by_id["current-near"].turn_index, by_id["current-near"].mixed_session) == (2, True)
