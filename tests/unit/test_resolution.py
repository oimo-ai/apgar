from __future__ import annotations

import pytest

from apgar.assembly.resolution import (
    configured_attribute_keys,
    resolve_agent_name,
    resolve_environment,
    resolve_prompt_version,
    resolve_release,
    resolve_session,
    resolve_surface,
)
from apgar.domain.settings import ReleaseSettings, SurfaceMapping
from tests.factories import make_agent
from tests.support import FIXTURE_NOW


@pytest.mark.parametrize(
    ("attrs", "expected"),
    [
        ({"gen_ai.agent.name": "Billing Copilot"}, "billing-copilot"),
        ({"agent.name": "Support Agent", "langfuse.trace.name": "other"}, "support-agent"),
        ({"langfuse.trace.name": "Trace Name", "resource.service.name": "svc"}, "trace-name"),
        ({"resource.gen_ai.agent.name": "From Resource"}, "from-resource"),
        ({"resource.service.name": "Service Name"}, "service-name"),
        ({}, None),
    ],
)
def test_agent_precedence(attrs: dict[str, str], expected: str | None) -> None:
    assert resolve_agent_name(attrs) == expected


@pytest.mark.parametrize(
    ("attrs", "settings", "expected"),
    [
        ({"apgar.release": " explicit "}, ReleaseSettings(), "explicit"),
        ({"gen_ai.agent.version": "a1b2c3d"}, ReleaseSettings(), "a1b2c3d"),
        ({"langfuse.release": "lf"}, ReleaseSettings(), "lf"),
        (
            {"resource.service.version": "v9", "gen_ai.agent.version": "other"},
            ReleaseSettings(from_attribute="service.version"),
            "v9",
        ),
        (
            {"custom.attr": "canary", "gen_ai.agent.version": "ignored"},
            ReleaseSettings(from_attribute="custom.attr"),
            "canary",
        ),
        ({"resource.service.version": "v9"}, ReleaseSettings(), "untagged"),
        ({}, ReleaseSettings(), "untagged"),
        ({"apgar.release": "x" * 200}, ReleaseSettings(), "x" * 128),
    ],
)
def test_release_precedence(
    attrs: dict[str, str], settings: ReleaseSettings, expected: str
) -> None:
    assert resolve_release(attrs, settings) == expected


@pytest.mark.parametrize(
    ("attrs", "expected"),
    [
        ({"apgar.environment": "prod"}, "prod"),
        ({"deployment.environment.name": "staging"}, "staging"),
        ({"deployment.environment": "dev"}, "dev"),
        ({"langfuse.environment": "production"}, "production"),
        ({"resource.deployment.environment.name": "qa"}, "qa"),
        ({}, "default"),
    ],
)
def test_environment_precedence(attrs: dict[str, str], expected: str) -> None:
    assert resolve_environment(attrs) == expected


def test_session_precedence() -> None:
    assert resolve_session({"apgar.session.id": "s-1"}, "trace") == ("s-1", False)
    assert resolve_session({"gen_ai.conversation.id": "c-1"}, "trace") == ("c-1", False)
    assert resolve_session({"session.id": "oi"}, "trace") == ("oi", False)
    assert resolve_session({"langfuse.session.id": "lf"}, "trace") == ("lf", False)
    assert resolve_session({}, "trace-id") == ("trace-id", True)


def test_prompt_version_precedence() -> None:
    root = {"langfuse.prompt.name": "billing", "langfuse.prompt.version": "7"}
    assert resolve_prompt_version(root, {"gen_ai.prompt.name": "other"}) == "billing@7"
    assert resolve_prompt_version({"langfuse.prompt.name": "billing"}, None) == "billing"
    assert resolve_prompt_version({"apgar.prompt.version": "pinned"}, None) == "pinned"
    assert resolve_prompt_version({}, {"gen_ai.prompt.name": "from-chat"}) == "from-chat"
    assert resolve_prompt_version({}, None) == ""


def test_surface_mapping() -> None:
    attrs = {
        "langfuse.trace.metadata.channel": "slack",
        "langfuse.trace.tags": '["surface:web","other"]',
    }
    assert resolve_surface(attrs, SurfaceMapping(from_attribute="metadata.channel")) == "slack"
    assert resolve_surface(attrs, SurfaceMapping(from_attribute="tag:surface:")) == "web"
    assert resolve_surface(attrs, SurfaceMapping()) == ""
    direct = {"apgar.surface": "telegram"}
    mapping = SurfaceMapping(from_attribute="metadata.channel")
    assert resolve_surface(direct, mapping) == "telegram"


def test_configured_attribute_keys() -> None:
    agents = [
        make_agent(
            FIXTURE_NOW,
            release_settings=ReleaseSettings(from_attribute="app.release"),
            surface_mapping=SurfaceMapping(from_attribute="app.channel"),
        ),
        make_agent(
            FIXTURE_NOW,
            release_settings=ReleaseSettings(),
            surface_mapping=SurfaceMapping(from_attribute="metadata.channel"),
        ),
        make_agent(
            FIXTURE_NOW,
            release_settings=ReleaseSettings(from_attribute="service.version"),
            surface_mapping=SurfaceMapping(from_attribute="tag:surface:"),
        ),
    ]
    assert configured_attribute_keys(agents) == {"app.release", "app.channel", "service.version"}
