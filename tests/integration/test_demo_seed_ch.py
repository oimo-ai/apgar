from __future__ import annotations

import time
from datetime import UTC, datetime

import pytest

from apgar.assembly.assembler import Assembler
from apgar.demo.generator import purge, seed
from apgar.normalize.normalizer import HmacKeys
from tests.support import ChDatabase

pytestmark = pytest.mark.integration


async def test_seed_counts_and_runtime(ch_database: ChDatabase) -> None:
    settings, event, meta = ch_database
    now = datetime(2026, 10, 8, 9, 30, tzinfo=UTC)
    assembler = Assembler(event, meta, settings, HmacKeys.from_settings(settings), lambda: now)
    started = time.perf_counter()
    summary = await seed(event, meta, settings, 2, 60, 42, now, assembler)
    elapsed = time.perf_counter() - started
    assert elapsed < 60
    assert summary["turns"] == 240
    assert set(summary["agents"]) == {"billing-copilot", "support-agent"}
    rows = await event.client.query("SELECT count() FROM turns FINAL")
    assert int(rows.result_rows[0][0]) == 240


async def test_purge_removes_everything(ch_database: ChDatabase) -> None:
    settings, event, meta = ch_database
    now = datetime(2026, 10, 8, 9, 30, tzinfo=UTC)
    assembler = Assembler(event, meta, settings, HmacKeys.from_settings(settings), lambda: now)
    await seed(event, meta, settings, 2, 20, 42, now, assembler)
    purged = await purge(event, meta, now)
    assert purged == 2
    for table in ("turns", "tool_calls", "trace_state"):
        rows = await event.client.query(f"SELECT count() FROM {table}")
        count = int(rows.result_rows[0][0])
        assert count == 0, table
    spans = await event.client.query("SELECT count() FROM spans")
    assert int(spans.result_rows[0][0]) == 0
    agents = await meta.list_agents()
    assert agents == []
