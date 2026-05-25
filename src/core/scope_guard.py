"""Scope-level mutation guards.

Personal context is a read-only aggregate of every Space/Crew the user
belongs to. Resources (connections, metrics, glossary terms,
enterprise relationships, agents, etc.) live exclusively inside a
Space or Crew — Personal exists only to browse and run AI analyses on
the union of everything the caller can reach.

Mutations that would create or edit something *owned by* Personal are
rejected here so attackers can't bypass the FE gates by hitting the
API directly. Reads are not affected.
"""

from __future__ import annotations

from typing import Optional

from src.core.exceptions import ForbiddenError


_PERSONAL_VALUES = {"personal", "PERSONAL"}


def assert_not_personal_scope(scope: Optional[str]) -> None:
    """Reject ``scope == "personal"`` on a mutation endpoint.

    Args:
        scope: The scope value the client posted. May be None on
            endpoints where scope is optional — we never reject None.

    Raises:
        ForbiddenError: When ``scope`` is the string "personal" (case
            insensitive). The FE hides the affordance; this guards the
            API surface against direct calls.
    """
    if scope is None:
        return
    if str(scope) in _PERSONAL_VALUES:
        raise ForbiddenError(
            "Personal context is read-only. Create or edit resources "
            "inside a Space or Crew."
        )


def assert_not_personal_flag(is_personal: Optional[bool]) -> None:
    """Reject mutations whose payload sets ``is_personal=True``.

    Some endpoints carry the scope as a boolean flag rather than a
    string field. Same rule applies — Personal does not own resources.
    """
    if bool(is_personal):
        raise ForbiddenError(
            "Personal context is read-only. Create or edit resources "
            "inside a Space or Crew."
        )
