from __future__ import annotations

from datetime import timedelta

import pytest

from tests.support import FIXTURE_NOW, ChDatabase, make_turn

pytestmark = pytest.mark.integration


async def test_dirty_agents_lists_agents_with_new_turns(ch_database: ChDatabase) -> None:
    _settings, event, _meta = ch_database
    now = FIXTURE_NOW
    await event.upsert_turns(
        [
            make_turn(now, turn_id="new", ingested_at=now - timedelta(minutes=1)),
            make_turn(
                now,
                turn_id="also-new",
                agent_id="other",
                ingested_at=now - timedelta(minutes=30),
            ),
            make_turn(
                now,
                turn_id="old",
                agent_id="stale",
                ingested_at=now - timedelta(days=1),
            ),
        ]
    )
    assert await event.dirty_agents(now - timedelta(hours=1), now) == ["agent", "other"]
