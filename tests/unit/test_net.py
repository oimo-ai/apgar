from __future__ import annotations

import socket

import pytest

from apgar import net


def _accepts(server: socket.socket, host: str, family: socket.AddressFamily) -> bool:
    port = server.getsockname()[1]
    with socket.socket(family, socket.SOCK_STREAM) as client:
        client.settimeout(2)
        return client.connect_ex((host, port)) == 0


def test_listen_socket_accepts_both_families() -> None:
    if not socket.has_dualstack_ipv6():
        pytest.skip("host has no IPv6")
    with net.listen_socket(0) as server:
        assert server.family == socket.AF_INET6
        assert _accepts(server, "127.0.0.1", socket.AF_INET)
        assert _accepts(server, "::1", socket.AF_INET6)


def test_listen_socket_falls_back_to_ipv4(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(socket, "has_dualstack_ipv6", lambda: False)
    with net.listen_socket(0) as server:
        assert server.family == socket.AF_INET
        assert _accepts(server, "127.0.0.1", socket.AF_INET)


@pytest.mark.parametrize(("dualstack", "expected"), [(True, "::"), (False, "0.0.0.0")])
def test_any_address(monkeypatch: pytest.MonkeyPatch, dualstack: bool, expected: str) -> None:
    monkeypatch.setattr(socket, "has_dualstack_ipv6", lambda: dualstack)
    assert net.any_address() == expected
