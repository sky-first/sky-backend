"""W8 — Tool registry.

Master plan §7.1. Every tool the LLM can invoke is declared here with a
permission requirement, a rate limit and the validator to run before
execution. The executor (wire-in PR, later) calls ``get_tool(name)`` and
uses the returned ``ToolSpec`` to authorise + validate + audit.

Only tools in this registry are callable. Everything else is rejected
with ``CHAT_TOOL_DENIED``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, Iterable, Optional, Tuple

from src.ai.tools.sql_guard import GuardedSQL, SQLGuardViolation, guard_sql


@dataclass(frozen=True)
class ToolSpec:
    name: str
    permissions: Tuple[str, ...]     # every perm must be held by the caller
    scope: str                       # "authorized_tables" | "current_page_id" | "none"
    rate_limit: Tuple[int, str]      # (count, window) — e.g. (60, "minute")
    audit_level: str                 # "info" | "high" | "critical"
    description: str
    validator: Optional[Callable[..., object]] = None


def _validate_sql_select(sql: str, authorized_tables: Iterable[str]) -> GuardedSQL:
    """Adapter — raises SQLGuardViolation."""
    return guard_sql(sql, authorized_tables=authorized_tables)


TOOL_REGISTRY: Dict[str, ToolSpec] = {
    "sql.select": ToolSpec(
        name="sql.select",
        permissions=("connection.read",),
        scope="authorized_tables",
        rate_limit=(60, "minute"),
        audit_level="info",
        description="Read-only SELECT against an authorised connection.",
        validator=_validate_sql_select,
    ),
    "widget.create": ToolSpec(
        name="widget.create",
        permissions=("dashboard.write",),
        scope="current_page_id",
        rate_limit=(10, "minute"),
        audit_level="high",
        description="Create a widget on the caller's current dashboard.",
    ),
    "insight.pin": ToolSpec(
        name="insight.pin",
        permissions=("dashboard.write",),
        scope="current_page_id",
        rate_limit=(20, "minute"),
        audit_level="info",
        description="Pin a generated insight to the caller's page.",
    ),
    "schema.describe": ToolSpec(
        name="schema.describe",
        permissions=("connection.read",),
        scope="authorized_tables",
        rate_limit=(30, "minute"),
        audit_level="info",
        description="Return schema metadata for an authorised table.",
    ),
}


def get_tool(name: str) -> ToolSpec:
    """Look up a tool. Raises ``ToolNotAllowed`` when absent.

    The lookup is case-sensitive and intentionally strict — no partial
    matches, no fuzzy — because a typo should fail loudly, not resolve
    to an adjacent tool.
    """
    spec = TOOL_REGISTRY.get(name)
    if spec is None:
        raise ToolNotAllowed(name)
    return spec


class ToolNotAllowed(Exception):
    """Caller asked for a tool that isn't in the registry."""

    code = "CHAT_TOOL_DENIED"

    def __init__(self, requested: str):
        self.requested = requested
        super().__init__(f"Tool `{requested}` is not in the allowlist.")


def all_tool_names() -> list[str]:
    """Convenience — used by the W3 scope layer to render
    ``available_tools``."""
    return sorted(TOOL_REGISTRY.keys())
