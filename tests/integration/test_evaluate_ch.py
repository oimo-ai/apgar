from __future__ import annotations

import asyncio

import pytest

from apgar.assembly.assembler import Assembler
from apgar.demo.generator import DEMO_CLOCK, seed, simulate_verdicts
from apgar.demo.scenarios import _A2, _A3, _B3, _B4
from apgar.normalize.normalizer import HmacKeys
from apgar.verdict.evaluate import Evaluator
from apgar.verdict.pool import InlinePool
from tests.support import ChDatabase

pytestmark = pytest.mark.integration


async def test_demo_verdicts(ch_database: ChDatabase) -> None:
    settings, event, meta = ch_database
    now = DEMO_CLOCK
    assembler = Assembler(event, meta, settings, HmacKeys.from_settings(settings), lambda: now)
    await seed(event, meta, settings, 14, 300, 42, now, assembler)
    evaluator = Evaluator(event, meta, settings, InlinePool(), lambda: now, [], asyncio.Lock())
    states = await simulate_verdicts(event, meta, settings, now, evaluator)
    billing = states["billing-copilot"]
    support = states["support-agent"]
    assert billing[_A2]["state"] == "FAIL"
    assert billing[_A2]["reason"] == "confirmed"
    assert support["9f8e7d6"]["state"] == "INCONCLUSIVE"
    assert support["9f8e7d6"]["reason"] == "window_elapsed"
    assert support[_B3]["state"] == "FAIL"
    # B4 has no injected regression and only its last day and a half of traffic.
    assert support[_B4]["state"] == "INCONCLUSIVE"
    assert support[_B4]["reason"] == "insufficient_power"
    assert billing["fp-c4b2a9e8d711"]["state"] == "PASS"
    agents = {agent.name: agent for agent in await meta.list_agents()}
    billing_agent = agents["billing-copilot"]
    release = await meta.get_release(billing_agent.id, _A2)
    assert release is not None
    failed = release.verdict_summary["failed_metrics"]
    assert failed[0]["id"] == "tool_error_rate"
    assert failed[0]["worst_slice"] == {"dimension": "tool", "value": "sql_query"}
    assert release.baseline_unverified is False
    support_agent = agents["support-agent"]
    b3 = await meta.get_release(support_agent.id, _B3)
    assert b3 is not None
    failing = {item["id"] for item in b3.verdict_summary["failed_metrics"]}
    assert {"tool_retry_rate", "loop_rate"} <= failing
    a3 = await meta.get_release(billing_agent.id, _A3)
    assert a3 is not None
    evaluations = await meta.list_evaluations(billing_agent.id, _A3, limit=1)
    assert evaluations
    depth = evaluations[0].slices["output_tokens_p50"]["session_depth"]["values"]
    assert depth[0]["value"] == "long"
    assert depth[0]["status"] == "FAIL"
    b2 = await meta.get_release(agents["support-agent"].id, "a1b2c3d")
    assert b2 is not None
    b2_eval = await meta.list_evaluations(agents["support-agent"].id, "a1b2c3d", limit=1)
    prompts = {
        row["value"]
        for family in b2_eval[0].slices.values()
        for row in family.get("prompt_version", {}).get("values", [])
        if row["value"]
    }
    assert len(prompts) == 2
