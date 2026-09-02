"""Loopback-only socket guard for the Streamlit child process.

Placed on the child's PYTHONPATH so CPython imports it automatically at
startup. The Playwright route handler only covers browser traffic; this makes
the server-side of the lane executably offline too. On install it runs a
self-test against a documentation-range address (TEST-NET-3, never routed) and
records the outcome in the marker file named by ``E2E_SOCKET_GUARD_MARKER`` so
the test suite can assert the guard is actually live in the child.
"""

from __future__ import annotations

import ipaddress
import os
import socket
from typing import Any

SELF_TEST_TARGET = ("203.0.113.7", 80)
LOOPBACK_HOSTNAMES = frozenset({"localhost", "localhost.localdomain", ""})


class NonLoopbackConnectionError(OSError):
    """Raised when the guarded process tries to leave the loopback interface."""


def _is_loopback(address: object) -> bool:
    if not isinstance(address, tuple) or not address:
        return True  # AF_UNIX and friends never leave the machine.
    host = address[0]
    if not isinstance(host, str):
        return False
    if host.lower() in LOOPBACK_HOSTNAMES:
        return True
    try:
        parsed = ipaddress.ip_address(host.split("%", 1)[0])
    except ValueError:
        return False  # A name that needs external resolution is not loopback.
    return parsed.is_loopback


def _install() -> None:
    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex

    def guarded_connect(self: socket.socket, address: Any) -> None:
        if not _is_loopback(address):
            raise NonLoopbackConnectionError(
                f"offline e2e lane: refused non-loopback connect to {address!r}"
            )
        real_connect(self, address)

    def guarded_connect_ex(self: socket.socket, address: Any) -> int:
        if not _is_loopback(address):
            raise NonLoopbackConnectionError(
                f"offline e2e lane: refused non-loopback connect_ex to {address!r}"
            )
        return real_connect_ex(self, address)

    socket.socket.connect = guarded_connect  # type: ignore[method-assign]
    socket.socket.connect_ex = guarded_connect_ex  # type: ignore[method-assign]


def _self_test() -> str:
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.connect(SELF_TEST_TARGET)
    except NonLoopbackConnectionError as error:
        return f"blocked {error}"
    else:
        return "NOT BLOCKED: guard is inactive"
    finally:
        probe.close()


_install()

_marker = os.environ.get("E2E_SOCKET_GUARD_MARKER")
if _marker:
    with open(_marker, "a", encoding="utf-8") as handle:
        handle.write(f"pid={os.getpid()} {_self_test()}\n")
