from __future__ import annotations

from datetime import timedelta

import pytest

from apgar.domain.models import TurnRow
from apgar.domain.sessions import compute_session_fields
from apgar.storage.clickhouse.client import load_sql
from tests.support import FIXTURE_NOW, ChDatabase, make_turn

pytestmark = pytest.mark.integration


def _turns() -> list[TurnRow]:
    now = FIXTURE_NOW
    rows = []
    for index in range(21):
        rows.append(
            make_turn(
                now,
                turn_id=f"long-{index:02d}",
                session_id="long",
                start_ts=now + timedelta(minutes=index),
                end_ts=now + timedelta(minutes=index, seconds=20),
            )
        )
    rows.extend(
        [
            make_turn(now, turn_id="mix-0", session_id="mixed", release="a", start_ts=now),
            make_turn(
                now,
                turn_id="mix-1",
                session_id="mixed",
                release="a",
                start_ts=now + timedelta(minutes=1),
            ),
            make_turn(
                now,
                turn_id="mix-2",
                session_id="mixed",
                release="b",
                start_ts=now + timedelta(minutes=2),
            ),
            make_turn(
                now,
                turn_id="inf-0",
                session_id="inferred",
                session_inferred=True,
                start_ts=now,
                end_ts=now + timedelta(seconds=10),
            ),
            make_turn(
                now,
                turn_id="inf-1",
                session_id="inferred",
                session_inferred=True,
                start_ts=now + timedelta(minutes=1),
            ),
            make_turn(
                now,
                turn_id="closed-0",
                session_id="closed",
                start_ts=now,
                end_ts=now + timedelta(seconds=10),
            ),
            make_turn(
                now,
                turn_id="open-0",
                session_id="open",
                start_ts=now + timedelta(hours=3),
                end_ts=now + timedelta(hours=3, seconds=10),
            ),
        ]
    )
    assert len(rows) == 28
    return rows


async def test_session_sql_matches_python(ch_database: ChDatabase) -> None:
    _settings, event, _meta = ch_database
    turns = _turns()
    await event.upsert_turns(turns)
    query_now = FIXTURE_NOW + timedelta(hours=2)
    sql = load_sql("session_fields").replace("__SCOPE__", "1")
    sql = (
        f"{sql}\nSELECT turn_id, turn_index, depth_bucket, mixed_session, session_closed "
        "FROM derived ORDER BY turn_id"
    )
    result = await event.client.query(
        sql,
        parameters={
            "agent_id": "agent",
            "lookback_start": FIXTURE_NOW - timedelta(days=1),
            "now": query_now,
        },
    )
    expected = compute_session_fields(turns, query_now)
    assert len(result.result_rows) == len(expected)
    names = [str(name) for name in result.column_names]
    for raw in result.result_rows:
        row = {names[index]: raw[index] for index in range(len(names))}
        fields = expected[str(row["turn_id"])]
        assert int(row["turn_index"]) == fields.turn_index
        assert str(row["depth_bucket"]) == fields.depth_bucket
        assert bool(int(row["mixed_session"])) is fields.mixed_session
        assert bool(int(row["session_closed"])) is fields.session_closed
