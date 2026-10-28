from __future__ import annotations

import socket

# Probes in an IPv6-only cluster reach the pod over IPv6, and a host with IPv6 turned
# off cannot open an IPv6 socket. Both servers listen on both families where they can.


def any_address() -> str:
    return "::" if socket.has_dualstack_ipv6() else "0.0.0.0"


def listen_socket(port: int) -> socket.socket:
    if socket.has_dualstack_ipv6():
        return socket.create_server(("::", port), family=socket.AF_INET6, dualstack_ipv6=True)
    return socket.create_server(("0.0.0.0", port))
