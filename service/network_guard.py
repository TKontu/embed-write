"""Network guard for the analysis service (SV-05, invariant I9).

Reports and corpus stay on the machine by default: outbound connections are denied unless the
destination is loopback or a host named by an explicit per-session remote opt-in. Every check fails
closed and never resolves names via DNS.

Unwired by design until SV-01 wires it into the analysis service.
"""

from __future__ import annotations

import contextlib
import ipaddress
import socket
from dataclasses import dataclass
from typing import Iterable, Iterator
from urllib.parse import urlsplit

_ALLOWED_SCHEMES = frozenset({"http", "https", "ws", "wss"})
_LOOPBACK_NAMES = frozenset({"localhost"})


class NetworkGuardError(PermissionError):
    """An outbound connection was denied by the network guard."""


@dataclass(frozen=True)
class NetworkPolicy:
    """Per-session network policy. The default allows loopback only."""

    remote_enabled: bool = False
    allowed_hosts: frozenset = frozenset()

    @classmethod
    def allow_remote(cls, hosts: Iterable[str]) -> "NetworkPolicy":
        """Explicit opt-in: allow loopback plus exactly the named remote hosts."""
        names = frozenset(_normalize(h) for h in hosts)
        if not names or "" in names:
            raise ValueError("remote opt-in must name at least one non-empty host")
        return cls(remote_enabled=True, allowed_hosts=names)


def _normalize(host: object) -> str:
    if not isinstance(host, str):
        return ""
    h = host.strip().lower()
    if h.startswith("[") and h.endswith("]"):
        h = h[1:-1]
    return h.rstrip(".")


def _is_loopback(host: str) -> bool:
    if host in _LOOPBACK_NAMES:
        return True
    try:
        return ipaddress.ip_address(host.split("%", 1)[0]).is_loopback
    except ValueError:
        return False


def check_host(host: object, port: object, policy: NetworkPolicy) -> None:
    """Raise NetworkGuardError unless a connection to host:port is allowed."""
    h = _normalize(host)
    if not h:
        raise NetworkGuardError(f"denied: empty or invalid host {host!r}")
    if not isinstance(port, int) or isinstance(port, bool) or not 0 <= port <= 65535:
        raise NetworkGuardError(f"denied: invalid port {port!r}")
    if _is_loopback(h):
        return
    if policy.remote_enabled and h in policy.allowed_hosts:
        return
    raise NetworkGuardError(f"denied: {h}:{port} is not loopback and not opted in")


def check_url(url: object, policy: NetworkPolicy) -> None:
    """Raise NetworkGuardError unless an outbound request to url is allowed."""
    if not isinstance(url, str) or not url.strip():
        raise NetworkGuardError(f"denied: invalid url {url!r}")
    try:
        parts = urlsplit(url.strip())
        port = parts.port
        host = parts.hostname
    except ValueError as exc:
        raise NetworkGuardError(f"denied: unparsable url {url!r}") from exc
    scheme = parts.scheme.lower()
    if scheme not in _ALLOWED_SCHEMES:
        raise NetworkGuardError(f"denied: scheme {scheme!r} in {url!r}")
    if port is None:
        port = 443 if scheme in ("https", "wss") else 80
    check_host(host, port, policy)


def _check_address(address: object, policy: NetworkPolicy) -> None:
    if not isinstance(address, tuple) or len(address) < 2:
        raise NetworkGuardError(f"denied: unsupported address {address!r}")
    check_host(address[0], address[1], policy)


@contextlib.contextmanager
def guard_sockets(policy: NetworkPolicy) -> Iterator[None]:
    """Patch socket connects so denied destinations raise before any packet is sent."""
    orig_connect = socket.socket.connect
    orig_connect_ex = socket.socket.connect_ex
    orig_create = socket.create_connection
    inet = (socket.AF_INET, socket.AF_INET6)

    def connect(self, address):
        if self.family in inet:
            _check_address(address, policy)
        return orig_connect(self, address)

    def connect_ex(self, address):
        if self.family in inet:
            _check_address(address, policy)
        return orig_connect_ex(self, address)

    def create_connection(address, *args, **kwargs):
        _check_address(address, policy)
        return orig_create(address, *args, **kwargs)

    socket.socket.connect = connect
    socket.socket.connect_ex = connect_ex
    socket.create_connection = create_connection
    try:
        yield
    finally:
        socket.socket.connect = orig_connect
        socket.socket.connect_ex = orig_connect_ex
        socket.create_connection = orig_create
