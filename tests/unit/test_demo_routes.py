from __future__ import annotations

import httpx

from apgar.domain.enums import JobRequestKind
from tests.support import MemStores


async def test_seed_enqueues(
    app_client: httpx.AsyncClient, admin_headers: dict[str, str], mem_stores: MemStores
) -> None:
    _events, meta = mem_stores
    seeded = await app_client.post("/api/v1/demo/seed", headers=admin_headers)
    assert seeded.status_code == 202
    status = await app_client.get("/api/v1/status")
    assert status.json()["demo_seeding"] is True
    jobs = await meta.pending_jobs(limit=20)
    assert any(job.kind is JobRequestKind.demo_seed for job in jobs)
