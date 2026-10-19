from __future__ import annotations

from fastapi import APIRouter, Request

from apgar.api.deps import authorize
from apgar.api.verdict_api import enqueue
from apgar.domain.enums import JobRequestKind

router = APIRouter()


@router.post("/api/v1/demo/seed", status_code=202)
async def seed_demo(request: Request) -> dict[str, str]:
    await authorize(request)
    await enqueue(
        request,
        "",
        "",
        JobRequestKind.demo_seed,
        {"days": 14, "turns_per_day": 300, "seed": 42},
    )
    return {"status": "queued"}
