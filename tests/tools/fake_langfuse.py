from __future__ import annotations

import argparse
import base64
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException, Request

from apgar.domain.time import from_iso, to_iso, utcnow


def _offset(cursor: str | None) -> int:
    if not cursor:
        return 0
    try:
        padded = cursor + ("=" * (-len(cursor) % 4))
        return int(base64.urlsafe_b64decode(padded.encode()).decode())
    except (ValueError, UnicodeError):
        return 0


def _cursor(offset: int) -> str:
    return base64.urlsafe_b64encode(str(offset).encode()).decode().rstrip("=")


def _as_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        if value.lower() == "true":
            return True
        if value.lower() == "false":
            return False
    return None


def _time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    return from_iso(value)


def _matches_clause(obs: dict[str, Any], clause: dict[str, Any]) -> bool:
    column = str(clause.get("column", ""))
    operator = str(clause.get("operator", ""))
    expected = clause.get("value")
    if column == "isRootObservation" and operator == "=":
        flag = _as_bool(expected)
        return flag is None or bool(obs.get("isRootObservation")) is flag
    if column == "startTime":
        start = _time(obs.get("startTime"))
        bound = _time(expected)
        if start is None or bound is None:
            return False
        if operator == ">=":
            return start >= bound
        if operator == "<":
            return start < bound
        if operator == "<=":
            return start <= bound
        return False
    if column == "traceName" and operator == "=":
        return obs.get("traceName") == expected
    if column == "tags" and operator == "all of":
        tags = obs.get("tags") or []
        if not isinstance(expected, list) or not isinstance(tags, list):
            return False
        return all(tag in tags for tag in expected)
    if column == "metadata" and operator == "=":
        metadata = obs.get("metadata") or {}
        if not isinstance(metadata, dict):
            return False
        return metadata.get(clause.get("key")) == expected
    if column == "environment" and operator == "any of":
        if not isinstance(expected, list):
            return False
        return obs.get("environment") in expected
    if column == "traceId" and operator == "any of":
        if not isinstance(expected, list):
            return False
        return obs.get("traceId") in expected
    return True


def select_observations(
    observations: list[dict[str, Any]], params: list[tuple[str, str]]
) -> tuple[list[dict[str, Any]], str | None]:
    grouped: dict[str, list[str]] = {}
    for key, value in params:
        grouped.setdefault(key, []).append(value)
    rows = list(observations)
    root_values = grouped.get("isRootObservation") or []
    root_flag = _as_bool(root_values[0] if root_values else None)
    if root_flag is not None:
        rows = [row for row in rows if bool(row.get("isRootObservation")) is root_flag]
    trace_ids = grouped.get("traceId") or []
    if trace_ids:
        rows = [row for row in rows if row.get("traceId") in trace_ids]
    start_values = grouped.get("fromStartTime") or []
    end_values = grouped.get("toStartTime") or []
    start_bound = _time(start_values[0] if start_values else None)
    end_bound = _time(end_values[0] if end_values else None)
    if start_bound is not None:
        rows = [
            row
            for row in rows
            if (start := _time(row.get("startTime"))) is not None and start >= start_bound
        ]
    if end_bound is not None:
        rows = [
            row
            for row in rows
            if (start := _time(row.get("startTime"))) is not None and start < end_bound
        ]
    for raw_filter in grouped.get("filter") or []:
        try:
            clauses = json.loads(raw_filter)
        except json.JSONDecodeError:
            continue
        if isinstance(clauses, list):
            rows = [
                row
                for row in rows
                if all(
                    _matches_clause(row, clause) for clause in clauses if isinstance(clause, dict)
                )
            ]
    rows.sort(key=lambda row: (str(row.get("startTime")), str(row.get("id"))))
    limit_raw = (grouped.get("limit") or ["1000"])[0]
    try:
        limit = max(0, int(limit_raw))
    except ValueError:
        limit = 1000
    cursor_values = grouped.get("cursor") or []
    offset = _offset(cursor_values[0] if cursor_values else None)
    page = rows[offset : offset + limit]
    nxt = offset + limit
    cursor = None if nxt >= len(rows) else _cursor(nxt)
    return page, cursor


def load_observations(path: Path, started: datetime) -> list[dict[str, Any]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise TypeError("observations_all.json must be a list")
    rows: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        obs = dict(item)
        if "startOffsetSeconds" in obs:
            start = started + timedelta(seconds=float(obs.pop("startOffsetSeconds")))
            obs["startTime"] = to_iso(start)
        if "endOffsetSeconds" in obs:
            end = started + timedelta(seconds=float(obs.pop("endOffsetSeconds")))
            obs["endTime"] = to_iso(end)
        rows.append(obs)
    return rows


def create_app(fixtures: Path, started: datetime | None = None) -> FastAPI:
    projects = json.loads((fixtures / "projects.json").read_text(encoding="utf-8"))
    observations = load_observations(fixtures / "observations_all.json", started or utcnow())
    app = FastAPI()

    def _auth(request: Request) -> None:
        header = request.headers.get("authorization", "")
        scheme, _, token = header.partition(" ")
        if scheme.lower() != "basic" or not token:
            raise HTTPException(status_code=401, detail="unauthorized")
        try:
            decoded = base64.b64decode(token).decode()
        except (ValueError, UnicodeError) as exc:
            raise HTTPException(status_code=401, detail="unauthorized") from exc
        username, _, password = decoded.partition(":")
        if username != "pk-test" or password != "sk-test":
            raise HTTPException(status_code=401, detail="unauthorized")

    @app.get("/api/public/projects")
    async def get_projects(request: Request) -> dict[str, Any]:
        _auth(request)
        if isinstance(projects, dict):
            return projects
        return {"data": projects}

    @app.get("/api/public/v2/observations")
    async def list_observations(request: Request) -> dict[str, Any]:
        _auth(request)
        pairs = list(request.query_params.multi_items())
        page, cursor = select_observations(observations, pairs)
        return {"data": page, "meta": {"cursor": cursor}}

    return app


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=9099)
    parser.add_argument(
        "--fixtures",
        type=Path,
        default=Path("tests/fixtures/langfuse"),
    )
    args = parser.parse_args()
    uvicorn.run(create_app(args.fixtures), host="0.0.0.0", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
