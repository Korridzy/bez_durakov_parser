"""Socket egress guard for the backend test suite.

The suite must stay green with the Compose stack down and no API key, so any
outbound connection other than loopback or the Compose-internal database host
is a defect in a test rather than an environment quirk. Blocking it loudly
keeps an accidental dependency on a live LiteLLM, a live OpenAI endpoint, or
any other host from hiding behind a passing run.

Standard library only, so every backend test process can install it.
"""
from __future__ import annotations

import importlib
import ipaddress
import socket
import sys
from typing import Any
from urllib.parse import urlsplit

# Parent of the mounted bd_shared directory, same convention as main.py:16.
sys.path.insert(0, '/')

_config = importlib.import_module("bd_shared.config")

_hostname = urlsplit(str(_config.DATABASE_URL)).hostname
if _hostname is None:
    raise RuntimeError(f"database URL carries no host: {_config.DATABASE_URL!r}")

# Under BD_DOCKER this is the Compose service host (`mysql`), which the
# GameDataService tests are allowed to reach when the stack happens to be up.
DATABASE_HOST: str = _hostname

_original_connect = socket.socket.connect
_original_connect_ex = socket.socket.connect_ex
_database_addresses: frozenset[str] | None = None


class BlockedEgressError(RuntimeError):
    """Raised when a test process attempts an unexpected outbound connection."""


def _database_addresses_once() -> frozenset[str]:
    """Resolve the database host once, tolerating a stack that is down."""
    global _database_addresses

    cached = _database_addresses
    if cached is None:
        try:
            resolved = socket.getaddrinfo(DATABASE_HOST, None)
        except socket.gaierror:
            # Stack down: the host has no address, so there is nothing to allow.
            resolved = []
        cached = frozenset(str(info[4][0]) for info in resolved)
        _database_addresses = cached

    return cached


def _is_allowed(family: int, address: object) -> bool:
    if family not in (socket.AF_INET, socket.AF_INET6):
        # Unix and other local families are not egress.
        return True
    if not isinstance(address, tuple):
        return True

    host = str(address[0])
    try:
        parsed = ipaddress.ip_address(host)
    except ValueError:
        return host == DATABASE_HOST

    return parsed.is_loopback or host in _database_addresses_once()


def _require_allowed(sock: socket.socket, address: object) -> None:
    if _is_allowed(sock.family, address):
        return

    message = (
        f"blocked outbound connection to {address!r}; offline tests may reach "
        f"only loopback and the Compose database host {DATABASE_HOST!r}"
    )
    print(f"NET GUARD: {message}", file=sys.stderr, flush=True)
    raise BlockedEgressError(message)


def _guarded_connect(self: socket.socket, address: Any, /) -> None:
    _require_allowed(self, address)
    _original_connect(self, address)


def _guarded_connect_ex(self: socket.socket, address: Any, /) -> int:
    _require_allowed(self, address)
    return _original_connect_ex(self, address)


def install() -> None:
    """Restrict this process to loopback and the Compose-internal database host."""
    socket.socket.connect = _guarded_connect
    socket.socket.connect_ex = _guarded_connect_ex
