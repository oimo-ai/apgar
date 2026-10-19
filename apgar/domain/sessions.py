from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta

from apgar.domain.models import TurnRow

_QUIET_WINDOW = timedelta(minutes=30)


@dataclass(slots=True)
class SessionFields:
    turn_index: int
    depth_bucket: str
    mixed_session: bool
    session_first_start: datetime
    session_closed: bool


def _depth(index: int) -> str:
    if index <= 5:
        return "short"
    if index <= 20:
        return "medium"
    return "long"


def compute_session_fields(turns: list[TurnRow], now: datetime) -> dict[str, SessionFields]:
    grouped: dict[str, list[TurnRow]] = defaultdict(list)
    for turn in turns:
        grouped[turn.session_id].append(turn)
    fields: dict[str, SessionFields] = {}
    for session in grouped.values():
        ordered = sorted(session, key=lambda item: (item.start_ts, item.turn_id))
        first = ordered[0].start_ts
        last_end = max(item.end_ts for item in ordered)
        closed = last_end + _QUIET_WINDOW < now
        seen: list[str] = []
        for index, turn in enumerate(ordered):
            mixed = any(release != turn.release for release in seen)
            seen.append(turn.release)
            fields[turn.turn_id] = SessionFields(
                turn_index=index + 1,
                depth_bucket=_depth(index + 1),
                mixed_session=mixed,
                session_first_start=first,
                session_closed=closed,
            )
    return fields
