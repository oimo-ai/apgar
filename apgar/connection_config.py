from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

from apgar.domain.enums import ConnectionType

_BULLET = "••••"
_SLACK_PREFIX = "https://hooks.slack.com/"


class ConnectionConfigError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def _http_url(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ConnectionConfigError(f"{field}: must be an http or https URL")
    text = value.rstrip("/")
    parts = urlsplit(text)
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        raise ConnectionConfigError(f"{field}: must be an http or https URL")
    return text


def _is_placeholder(value: object) -> bool:
    return isinstance(value, str) and _BULLET in value


def _merge_secret(
    raw: dict[str, Any],
    field: str,
    previous: dict[str, Any] | None,
) -> str | None:
    if field not in raw:
        if previous is None:
            return None
        stored = previous.get(field)
        return stored if isinstance(stored, str) else None
    value = raw[field]
    if _is_placeholder(value):
        if previous is None:
            raise ConnectionConfigError(f"{field}: is required")
        stored = previous.get(field)
        if not isinstance(stored, str) or not stored:
            raise ConnectionConfigError(f"{field}: is required")
        return stored
    if not isinstance(value, str) or not value:
        raise ConnectionConfigError(f"{field}: is required")
    return value


def parse_config(
    conn_type: ConnectionType,
    raw: dict[str, Any],
    *,
    allow_insecure_slack: bool,
    previous: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if conn_type is ConnectionType.langfuse:
        secret = _merge_secret(raw, "secret_key", previous)
        if secret is None:
            raise ConnectionConfigError("secret_key: is required")
        public_key = raw.get("public_key", None if previous is None else previous.get("public_key"))
        host = raw.get("host", None if previous is None else previous.get("host"))
        if not isinstance(public_key, str) or not public_key:
            raise ConnectionConfigError("public_key: is required")
        default_fetch = True if previous is None else previous.get("fetch_content", True)
        fetch = raw.get("fetch_content", default_fetch)
        if not isinstance(fetch, bool):
            raise ConnectionConfigError("fetch_content: must be a boolean")
        project_id = ""
        if previous is not None and isinstance(previous.get("project_id"), str):
            project_id = str(previous["project_id"])
        return {
            "host": _http_url(host, "host"),
            "public_key": public_key,
            "secret_key": secret,
            "project_id": project_id,
            "fetch_content": fetch,
        }
    if conn_type is ConnectionType.slack:
        webhook = raw.get("webhook_url", None if previous is None else previous.get("webhook_url"))
        if not isinstance(webhook, str) or not webhook:
            raise ConnectionConfigError("webhook_url: is required")
        if not webhook.startswith(_SLACK_PREFIX) and not (
            allow_insecure_slack and webhook.startswith("http")
        ):
            raise ConnectionConfigError("webhook_url: must start with https://hooks.slack.com/")
        return {"webhook_url": webhook}
    secret = _merge_secret(raw, "secret", previous)
    if secret is None:
        raise ConnectionConfigError("secret: is required")
    if not 16 <= len(secret) <= 256:
        raise ConnectionConfigError("secret: must be 16 to 256 characters")
    url = raw.get("url", None if previous is None else previous.get("url"))
    return {"url": _http_url(url, "url"), "secret": secret}


_PUBLIC_PREFIXES = ("sk-lf-",)


def _mask(secret: str) -> str:
    if len(secret) < 12:
        return _BULLET
    prefix = next((item for item in _PUBLIC_PREFIXES if secret.startswith(item)), "")
    return prefix + _BULLET + secret[-4:]


def redact_config(conn_type: ConnectionType, config: dict[str, Any]) -> dict[str, Any]:
    if conn_type is ConnectionType.langfuse:
        secret = str(config.get("secret_key", ""))
        return {
            "host": config.get("host"),
            "public_key": config.get("public_key"),
            "project_id": config.get("project_id") or None,
            "fetch_content": bool(config.get("fetch_content", True)),
            "secret_key": _mask(secret),
        }
    if conn_type is ConnectionType.slack:
        return {"webhook_url": config.get("webhook_url")}
    return {"url": config.get("url"), "secret": _BULLET}


def config_material(config: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in config.items() if key != "project_id"}
