from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

from apgar.domain.enums import JobRequestKind, ReasonCode
from apgar.storage.memory import InMemoryEventStore, InMemoryMetaStore
from apgar.storage.types import ReleaseFilters
from apgar.worker.jobs.release_discovery import ReleaseDiscovery
from apgar.worker.jobs.rollup import RollupJob
from tests.factories import make_agent, make_release
from tests.support import make_turn


def _discovery(meta: InMemoryMetaStore) -> ReleaseDiscovery:
    return ReleaseDiscovery(meta, asyncio.Lock())


async def test_registration_reasons(fixed_now: datetime) -> None:
    meta = InMemoryMetaStore()
    agent = make_agent(fixed_now, environment="")
    await meta.upsert_agent(agent)
    discovery = _discovery(meta)
    first = make_turn(
        fixed_now, agent_id=agent.id, release="a1b2c3d", environment="production", late=False
    )
    await discovery.on_turn_assembled(first, agent, fixed_now)
    stored = await meta.get_release(agent.id, "a1b2c3d")
    assert stored is not None
    assert stored.reason is ReasonCode.no_baseline
    assert stored.first_seen == first.start_ts
    jobs = await meta.pending_jobs(10)
    assert len(jobs) == 1
    assert jobs[0].kind is JobRequestKind.evaluate
    await discovery.on_turn_assembled(first, agent, fixed_now)
    assert len(await meta.pending_jobs(10)) == 1
    later = make_turn(
        fixed_now + timedelta(hours=1),
        agent_id=agent.id,
        release="rel-two",
        environment="production",
        late=False,
    )
    await discovery.on_turn_assembled(later, agent, fixed_now)
    second = await meta.get_release(agent.id, "rel-two")
    assert second is not None
    assert second.reason is ReasonCode.insufficient_sample


async def test_ignored_turns(fixed_now: datetime) -> None:
    meta = InMemoryMetaStore()
    agent = make_agent(fixed_now, environment="production")
    await meta.upsert_agent(agent)
    discovery = _discovery(meta)
    for turn in (
        make_turn(fixed_now, agent_id=agent.id, release="untagged", environment="production"),
        make_turn(
            fixed_now,
            agent_id=agent.id,
            release="late-rel",
            late=True,
            environment="production",
        ),
        make_turn(fixed_now, agent_id=agent.id, release="stage-rel", environment="staging"),
    ):
        await discovery.on_turn_assembled(turn, agent, fixed_now)
    assert await meta.list_releases(ReleaseFilters(agent_id=agent.id)) == []


async def test_out_of_order_turns_keep_the_earliest_first_seen(fixed_now: datetime) -> None:
    meta = InMemoryMetaStore()
    agent = make_agent(fixed_now, environment="")
    await meta.upsert_agent(agent)
    discovery = _discovery(meta)
    later = make_turn(
        fixed_now + timedelta(hours=2),
        agent_id=agent.id,
        release="a1b2c3d",
        environment="production",
    )
    earlier = make_turn(fixed_now, agent_id=agent.id, release="a1b2c3d", environment="production")
    await discovery.on_turn_assembled(later, agent, fixed_now)
    await discovery.on_turn_assembled(earlier, agent, fixed_now + timedelta(seconds=1))
    stored = await meta.get_release(agent.id, "a1b2c3d")
    assert stored is not None
    assert stored.first_seen == earlier.start_ts


async def test_older_rollup_clock_keeps_release_fields(fixed_now: datetime) -> None:
    event = InMemoryEventStore()
    meta = InMemoryMetaStore()
    agent = make_agent(fixed_now, environment="")
    await meta.upsert_agent(agent)
    stamped = fixed_now + timedelta(seconds=10)
    await meta.upsert_release(
        make_release(
            stamped,
            agent_id=agent.id,
            release="a1b2c3d",
            first_seen=fixed_now,
            selected_baseline_release="v1",
            updated_at=stamped,
        )
    )
    await event.upsert_turns(
        [make_turn(fixed_now, agent_id=agent.id, release="a1b2c3d", ingested_at=fixed_now)]
    )
    await RollupJob(event, meta, asyncio.Lock()).run(fixed_now + timedelta(seconds=5))
    stored = await meta.get_release(agent.id, "a1b2c3d")
    assert stored is not None
    assert stored.selected_baseline_release == "v1"
    assert stored.last_seen == fixed_now
    assert stored.turn_count == 1
    assert stored.updated_at > stamped
