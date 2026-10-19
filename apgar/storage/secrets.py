from __future__ import annotations

import json
from typing import Any

from apgar.security import SecretBox


def seal_config(config: dict[str, Any], box: SecretBox | None) -> str:
    payload = json.dumps(config, separators=(",", ":"), sort_keys=True).encode()
    if box is None:
        return payload.decode()
    return box.encrypt(payload)


def open_config(raw: str | bytes, box: SecretBox | None) -> dict[str, Any]:
    text = raw.decode() if isinstance(raw, bytes) else raw
    if text == "":
        return {}
    loaded = json.loads(text) if box is None else json.loads(box.decrypt(text))
    if not isinstance(loaded, dict):
        raise TypeError("connection config must be a JSON object")
    return loaded
