from __future__ import annotations

import re
from uuid import uuid4

from fastapi import APIRouter, Query, Request, Response

from apgar.api.deps import authorize
from apgar.api.errors import ApiError
from apgar.api.schemas import IngestTokenIn
from apgar.domain.models import IngestToken
from apgar.domain.time import to_iso
from apgar.security import generate_token, hash_token, token_prefix

router = APIRouter()
_SLUG = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")


def _out(token: IngestToken, agent: str | None) -> dict[str, object]:
    return {
        "id": token.id,
        "name": token.name,
        "token_prefix": token.token_prefix,
        "agent": agent,
        "auto_create_agents": token.auto_create_agents,
        "created_at": to_iso(token.created_at),
        "revoked_at": None if token.revoked_at is None else to_iso(token.revoked_at),
    }


async def _agent_slug(request: Request, agent_id: str) -> str | None:
    if not agent_id:
        return None
    agent = await request.app.state.meta_store.get_agent(agent_id)
    if agent is None:
        return None
    return str(agent.name)


@router.get("/api/v1/ingest-tokens")
async def list_ingest_tokens(
    request: Request,
    limit: int = Query(default=50, ge=0, le=500),
    offset: int = Query(default=0, ge=0),
) -> dict[str, object]:
    await authorize(request)
    tokens = await request.app.state.meta_store.list_ingest_tokens()
    page = tokens[offset : offset + limit]
    items = [_out(token, await _agent_slug(request, token.agent_id)) for token in page]
    return {"items": items, "total": len(tokens)}


@router.post("/api/v1/ingest-tokens", status_code=201)
async def create_ingest_token(request: Request, body: IngestTokenIn) -> dict[str, object]:
    await authorize(request)
    agent_id = ""
    agent_slug: str | None = None
    if body.agent is not None:
        if _SLUG.fullmatch(body.agent) is None:
            raise ApiError("validation_error", 422, "agent slug is invalid")
        agent = await request.app.state.meta_store.get_agent_by_name(body.agent)
        if agent is None:
            raise ApiError("not_found", 404, "agent not found")
        agent_id = agent.id
        agent_slug = agent.name
    now = request.app.state.clock()
    plaintext = generate_token("apg_ing_")
    token = IngestToken(
        id=str(uuid4()),
        name=body.name,
        token_hash=hash_token(plaintext),
        token_prefix=token_prefix(plaintext),
        agent_id=agent_id,
        auto_create_agents=body.auto_create_agents,
        created_at=now,
        revoked_at=None,
        updated_at=now,
    )
    await request.app.state.meta_store.upsert_ingest_token(token)
    return {**_out(token, agent_slug), "token": plaintext}


@router.delete("/api/v1/ingest-tokens/{token_id}", status_code=204)
async def revoke_ingest_token(request: Request, token_id: str) -> Response:
    await authorize(request)
    tokens = await request.app.state.meta_store.list_ingest_tokens()
    found = next((token for token in tokens if token.id == token_id), None)
    if found is None:
        raise ApiError("not_found", 404, "ingest token not found")
    now = request.app.state.clock()
    revoked = IngestToken(
        id=found.id,
        name=found.name,
        token_hash=found.token_hash,
        token_prefix=found.token_prefix,
        agent_id=found.agent_id,
        auto_create_agents=found.auto_create_agents,
        created_at=found.created_at,
        revoked_at=now,
        updated_at=now,
    )
    await request.app.state.meta_store.upsert_ingest_token(revoked)
    return Response(status_code=204)
