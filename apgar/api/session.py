from __future__ import annotations

import base64
import hmac
import json
import secrets
from datetime import datetime

from apgar.security import derive_key, hmac_sha256

_SESSION_INFO = b"session-cookie"
_MAX_AGE = 86400


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _b64decode(token: str) -> bytes:
    padded = token + ("=" * (-len(token) % 4))
    return base64.urlsafe_b64decode(padded.encode())


def issue_session(secret_key: str, now: datetime) -> str:
    iat = int(now.timestamp())
    payload = {"exp": iat + _MAX_AGE, "iat": iat, "nonce": secrets.token_hex(8)}
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    signature = hmac_sha256(derive_key(secret_key, _SESSION_INFO), raw)
    return _b64encode(raw) + "." + _b64encode(signature)


def verify_session_cookie(value: str, secret_key: str, now: datetime) -> bool:
    payload_text, separator, signature_text = value.partition(".")
    if separator == "" or "." in signature_text:
        return False
    try:
        raw = _b64decode(payload_text)
        signature = _b64decode(signature_text)
    except Exception:
        return False
    # urlsafe_b64decode ignores the last character's unused bits and non-alphabet
    # characters, so many different strings decode to the same HMAC.
    if _b64encode(raw) != payload_text or _b64encode(signature) != signature_text:
        return False
    expected = hmac_sha256(derive_key(secret_key, _SESSION_INFO), raw)
    if len(signature) != len(expected):
        return False
    if not hmac.compare_digest(signature, expected):
        return False
    try:
        payload = json.loads(raw)
        exp = int(payload["exp"])
    except (TypeError, ValueError, KeyError, json.JSONDecodeError):
        return False
    return int(now.timestamp()) < exp
