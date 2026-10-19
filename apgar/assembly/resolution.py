from __future__ import annotations

import json
from collections.abc import Iterable, Sequence

from apgar.domain.models import Agent
from apgar.domain.naming import slugify
from apgar.domain.settings import ReleaseSettings, SurfaceMapping
from apgar.normalize.mapping import (
    AGENT_NAME_CHAIN,
    ENVIRONMENT_CHAIN,
    RELEASE_CHAIN,
    SESSION_CHAIN,
)


def lookup(attrs: dict[str, str], chain: Sequence[str]) -> str | None:
    for key in chain:
        value = attrs.get(key, "")
        if value:
            return value
    for key in chain:
        value = attrs.get(f"resource.{key}", "")
        if value:
            return value
    return None


def resolve_agent_name(attrs: dict[str, str]) -> str | None:
    found = lookup(attrs, AGENT_NAME_CHAIN)
    if found is None:
        return None
    return slugify(found)


def resolve_release(attrs: dict[str, str], release_settings: ReleaseSettings) -> str:
    if release_settings.from_attribute:
        found = lookup(attrs, [release_settings.from_attribute])
    else:
        found = lookup(attrs, RELEASE_CHAIN)
    if not found:
        return "untagged"
    text = found.strip()[:128]
    return text or "untagged"


def resolve_environment(attrs: dict[str, str]) -> str:
    return lookup(attrs, ENVIRONMENT_CHAIN) or "default"


def resolve_session(attrs: dict[str, str], trace_id: str) -> tuple[str, bool]:
    found = lookup(attrs, SESSION_CHAIN)
    if found is None:
        return trace_id, True
    return found, False


def _prompt_from(attrs: dict[str, str]) -> str | None:
    name = attrs.get("langfuse.prompt.name", "")
    if name:
        version = attrs.get("langfuse.prompt.version", "")
        return f"{name}@{version}" if version else name
    pinned = attrs.get("apgar.prompt.version", "")
    if pinned:
        return pinned
    gen_ai = attrs.get("gen_ai.prompt.name", "")
    if gen_ai:
        return gen_ai
    return None


def resolve_prompt_version(
    root_attrs: dict[str, str],
    first_chat_attrs: dict[str, str] | None,
) -> str:
    for attrs in (root_attrs, first_chat_attrs):
        if not attrs:
            continue
        found = _prompt_from(attrs)
        if found:
            return found
    return ""


def _tag_value(raw: str, prefix: str) -> str:
    if not raw:
        return ""
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return ""
    if not isinstance(parsed, list):
        return ""
    for item in parsed:
        if isinstance(item, str) and item.startswith(prefix):
            return item[len(prefix) :]
    return ""


def resolve_surface(attrs: dict[str, str], mapping: SurfaceMapping) -> str:
    direct = attrs.get("apgar.surface", "")
    if direct:
        return direct[:64]
    source = mapping.from_attribute
    if not source:
        return ""
    if source.startswith("metadata."):
        value = attrs.get("langfuse.trace.metadata." + source.removeprefix("metadata."), "")
    elif source.startswith("tag:"):
        value = _tag_value(attrs.get("langfuse.trace.tags", ""), source.removeprefix("tag:"))
    else:
        value = attrs.get(source, "")
    return value[:64]


def configured_attribute_keys(agents: Iterable[Agent]) -> frozenset[str]:
    keys: set[str] = set()
    for agent in agents:
        release = agent.release_settings.from_attribute
        if release:
            keys.add(release)
        surface = agent.surface_mapping.from_attribute
        if surface and not surface.startswith(("metadata.", "tag:")):
            keys.add(surface)
    return frozenset(keys)
