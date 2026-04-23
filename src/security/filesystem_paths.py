"""Guard against path-traversal / sensitive-file access when users
pass filesystem paths that the server will open.

Red-team finding CR-003 (2026-04-23): the SQLite connector accepted
``../../../../etc/passwd`` and seven sibling traversal payloads. The
SQLite driver wouldn't actually return `/etc/passwd` contents (it'd
fail with "file is not a database"), but the surface is wide:

  - a malicious read-only .sqlite planted in a world-readable dir
    becomes a data-exfil vector,
  - the server burns file-descriptor open() syscalls on attacker-
    controlled paths,
  - log lines include the path, which can help enumerate the FS.

Policy:

- Reject any path containing ``..`` (with or without URL-encoding /
  backslash variants).
- Reject NUL bytes (``%00`` / literal).
- Reject paths that resolve into known-sensitive prefixes (``/etc``,
  ``/proc``, ``/sys``, ``/root``, ``/var/log``). This list is a
  defence against lucky edge cases — the allowlist below is the
  primary gate.
- When ``SQLITE_ALLOWED_PREFIXES`` is set (colon-separated absolute
  dirs), the resolved realpath MUST be under one of them.
- Windows-style separators (``\\``) are rejected outright — we don't
  deploy on Windows, accepting them silently would only be a bypass
  vector.
"""

from __future__ import annotations

import os
from typing import Iterable

SENSITIVE_PREFIXES = (
    "/etc/",
    "/proc/",
    "/sys/",
    "/root/",
    "/var/log/",
    "/var/secrets/",
    "/run/secrets/",
    "/home/",  # user homes often contain credentials
)


class UnsafePathError(ValueError):
    """Raised when a user-supplied local path looks like traversal /
    sensitive / out-of-allowlist."""


def _contains_traversal(path: str) -> bool:
    lowered = path.lower()
    for marker in (
        "..",
        "%2e%2e",
        "%2e%2e%2f",
        "%2e%2e/",
        "..%2f",
        "\\..\\",
        "..\\",
        "....//",
        "..;/",
    ):
        if marker in lowered:
            return True
    return False


def _allowed_prefixes_from_env() -> Iterable[str]:
    raw = os.environ.get("SQLITE_ALLOWED_PREFIXES", "").strip()
    if not raw:
        return ()
    return tuple(
        os.path.abspath(p.strip())
        for p in raw.split(":")
        if p.strip()
    )


def validate_sqlite_path(path: str) -> str:
    """Validate and return ``path`` when safe; raise UnsafePathError otherwise."""
    if not isinstance(path, str) or not path:
        raise UnsafePathError("path is empty")
    if "\x00" in path or "%00" in path.lower():
        raise UnsafePathError("NUL byte in path")
    if "\\" in path:
        raise UnsafePathError("backslash is not allowed in path")
    if _contains_traversal(path):
        raise UnsafePathError("path traversal not allowed")

    # Reject sensitive prefixes before realpath — catches direct
    # ``/etc/passwd`` without having to stat anything.
    for bad in SENSITIVE_PREFIXES:
        if path.startswith(bad) or path == bad.rstrip("/"):
            raise UnsafePathError(f"path in blocked prefix {bad!r}")

    # If ops has set an allowlist, require the resolved realpath to
    # live under one of them. Note: realpath() may follow a symlink;
    # attackers who can plant symlinks have broader compromise, but
    # the allowlist still contains the blast radius.
    allowed = tuple(_allowed_prefixes_from_env())
    if allowed:
        real = os.path.realpath(path)
        if not any(
            real == prefix or real.startswith(prefix.rstrip("/") + "/")
            for prefix in allowed
        ):
            raise UnsafePathError(
                f"path {real!r} is outside SQLITE_ALLOWED_PREFIXES ({allowed})"
            )

    return path
