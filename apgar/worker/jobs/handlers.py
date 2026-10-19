from __future__ import annotations

from datetime import datetime

from apgar.assembly.assembler import Assembler
from apgar.config import Settings
from apgar.domain.models import JobRequest
from apgar.domain.time import utcnow
from apgar.normalize.normalizer import HmacKeys
from apgar.storage.interfaces import EventStore, MetaStore
from apgar.verdict.evaluate import Evaluator


class EvaluateHandler:
    def __init__(self, evaluator: Evaluator, meta_store: MetaStore) -> None:
        self._evaluator = evaluator
        self._meta = meta_store

    async def handle(self, job: JobRequest, now: datetime) -> None:
        agent = await self._meta.get_agent(job.agent_id)
        if agent is None or agent.is_demo:
            return
        release = await self._meta.get_release(job.agent_id, job.release)
        if release is None:
            return
        await self._evaluator.evaluate_release(agent, release, now, False)


class ApplyEventsHandler:
    def __init__(self, evaluator: Evaluator, meta_store: MetaStore) -> None:
        self._evaluator = evaluator
        self._meta = meta_store

    async def handle(self, job: JobRequest, now: datetime) -> None:
        agent = await self._meta.get_agent(job.agent_id)
        if agent is None:
            return
        release = await self._meta.get_release(job.agent_id, job.release)
        if release is None:
            return
        events = await self._meta.release_events(job.agent_id, job.release)
        needs_eval = any(
            release.verdict_updated_at is None or event.ts > release.verdict_updated_at
            for event in events
        )
        if needs_eval:
            await self._evaluator.evaluate_release(agent, release, now, True)


class DemoSeedHandler:
    def __init__(
        self,
        event_store: EventStore,
        meta_store: MetaStore,
        settings: Settings,
        evaluator: Evaluator,
    ) -> None:
        self._events = event_store
        self._meta = meta_store
        self._settings = settings
        self._evaluator = evaluator

    async def handle(self, job: JobRequest, now: datetime) -> None:
        if job.agent_id:
            agent = await self._meta.get_agent(job.agent_id)
            if agent is None:
                return
        from apgar.demo.generator import seed, simulate_verdicts

        days = int(job.payload.get("days", 14))
        turns = int(job.payload.get("turns_per_day", 300))
        seed_value = int(job.payload.get("seed", 42))
        assembler = Assembler(
            self._events,
            self._meta,
            self._settings,
            HmacKeys.from_settings(self._settings),
            utcnow,
        )
        await seed(
            self._events, self._meta, self._settings, days, turns, seed_value, now, assembler
        )
        await simulate_verdicts(
            self._events, self._meta, self._settings, now, self._evaluator, notify=False
        )
