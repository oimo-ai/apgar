from __future__ import annotations

from datetime import UTC, datetime, timedelta


def utcnow() -> datetime:
    return datetime.now(UTC)


def to_iso(dt: datetime) -> str:
    aware = dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)
    millis = aware.microsecond // 1000
    return f"{aware.strftime('%Y-%m-%dT%H:%M:%S')}.{millis:03d}Z"


def from_iso(value: str) -> datetime:
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def monotonic_updated_at(now: datetime, current: datetime | None) -> datetime:
    """Stamp a ReplacingMergeTree row so this write is the one FINAL keeps.

    A job receives `now` when its run starts. Another job can commit a later
    stamp before this one reaches `release_lock`.
    """
    if current is None or now > current:
        return now
    return current + timedelta(microseconds=1)
