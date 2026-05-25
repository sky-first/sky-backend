"""Defence against SSRF / file:/ gopher:/ schemes when users pass URLs
that the server will fetch on their behalf.

Red-team finding CR-002 (2026-04-23): the REST connector accepted
``http://169.254.169.254/latest/meta-data/`` as ``base_url``,
creating a credentialed SSRF path to cloud instance metadata. This
module is the single choke-point: any schema that stores a URL the
server will later fetch should call :func:`validate_outbound_url`.

Policy:

- Scheme must be ``http`` or ``https``. ``file``, ``gopher``, ``dict``,
  ``ftp`` are rejected unconditionally.
- Host must resolve away from the loopback, link-local, private RFC
  1918 and cloud-metadata address ranges. We do the DNS resolution
  *at validation time*, which does not prevent DNS-rebinding attacks
  that swap the IP at connect time — the runtime guard in
  :func:`validate_outbound_url` is a second layer to call from the
  connector at fetch time. (See TODO below.)
- Host must not be a bare IP literal in the private ranges either.
- Userinfo (``user@host``) is rejected — used for phishing tricks.

TODO: the connector should, at fetch time, bind the socket to an IP
resolved through a restricted resolver (or simply post-connect
re-validate the peer IP). Landing that is a separate follow-up to
close the DNS-rebinding window.
"""

from __future__ import annotations

import ipaddress
import socket
from typing import Iterable
from urllib.parse import urlparse

from fastapi import HTTPException, status


BLOCKED_NETWORKS: tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...] = (
    # Loopback
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("::1/128"),
    # Link-local — IMDS lives here
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("fe80::/10"),
    # RFC 1918 private
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    # Carrier-grade NAT
    ipaddress.ip_network("100.64.0.0/10"),
    # Unspecified / broadcast / etc.
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("224.0.0.0/4"),  # multicast
    ipaddress.ip_network("240.0.0.0/4"),  # reserved
    # IPv6 ULA
    ipaddress.ip_network("fc00::/7"),
)

# Hostnames that humans aim at when doing SSRF. Covered indirectly by
# the IP check after DNS resolution — but we also refuse them by name
# so a broken/absent resolver doesn't create a bypass.
BLOCKED_HOSTNAMES = {
    "localhost",
    "ip6-localhost",
    "metadata.google.internal",
    "metadata.goog",
    "metadata",
}

ALLOWED_SCHEMES = frozenset({"http", "https"})


class UnsafeURLError(ValueError):
    """Raised when a user-supplied URL targets a blocked scheme/host."""


def _resolve_all(host: str) -> Iterable[str]:
    """Return every A/AAAA record for ``host``. Catches a resolver
    that returns multiple answers (split-horizon, dual-stack)."""
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError as exc:  # pragma: no cover - network issue path
        raise UnsafeURLError(f"could not resolve host {host!r}: {exc}")
    return {info[4][0] for info in infos}


def _is_blocked_ip(ip_str: str) -> bool:
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return False
    return any(ip in net for net in BLOCKED_NETWORKS)


def validate_outbound_url(url: str, *, allow_private: bool = False) -> str:
    """Validate + canonicalise an outbound URL. Raises
    :class:`UnsafeURLError` on any violation.

    Use ``allow_private=True`` only when the caller explicitly wants
    to target an internal host (e.g. an on-prem connector). That knob
    should be guarded by a feature flag + audit log, never exposed
    directly to end users.
    """
    if not isinstance(url, str) or not url:
        raise UnsafeURLError("URL is empty")
    parsed = urlparse(url)

    if parsed.scheme.lower() not in ALLOWED_SCHEMES:
        raise UnsafeURLError(
            f"scheme {parsed.scheme!r} is not allowed — only http/https"
        )
    if parsed.username or parsed.password:
        raise UnsafeURLError("userinfo in URL is not allowed")

    host = (parsed.hostname or "").lower()
    if not host:
        raise UnsafeURLError("URL has no host")
    if host in BLOCKED_HOSTNAMES:
        raise UnsafeURLError(f"host {host!r} is blocked")

    if allow_private:
        return url

    # Literal IP?
    try:
        ip = ipaddress.ip_address(host)
        if _is_blocked_ip(str(ip)):
            raise UnsafeURLError(f"IP {host} is in a blocked range")
        return url
    except ValueError:
        pass  # hostname, resolve below

    for resolved in _resolve_all(host):
        if _is_blocked_ip(resolved):
            raise UnsafeURLError(
                f"host {host!r} resolves to blocked address {resolved}"
            )

    return url


def validate_outbound_url_or_400(url: str, *, allow_private: bool = False) -> str:
    """FastAPI-friendly wrapper: raises HTTPException(400) instead of
    UnsafeURLError so it maps cleanly to a 400 response without
    leaking a stacktrace."""
    try:
        return validate_outbound_url(url, allow_private=allow_private)
    except UnsafeURLError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"URL rejected: {exc}",
        )
