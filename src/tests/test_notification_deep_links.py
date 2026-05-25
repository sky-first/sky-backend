"""Regression pinning for notification deep-link shapes.

Two user-reported 2026-04-16 bugs:

  * Agent notifications linked to /dashboard/sky-studio (renamed to
    /dashboard/universe-intelligence). Clicks 404'd.

  * Comment @mention notifications linked to /dashboards/<id>
    (plural). The frontend route is /dashboard?id=<id> (singular).
    Clicks silently went nowhere.

These tests pin the exact producer shapes so a future rename breaks
CI instead of breaking end users.
"""

from __future__ import annotations

import inspect

from src.services import comment_service
from src.workers import agent_worker


def test_agent_worker_deep_link_uses_universe_intelligence_route():
    src = inspect.getsource(agent_worker)
    assert "/dashboard/universe-intelligence?agent=" in src, (
        "agent_worker no longer points at the universe-intelligence "
        "route — clicking an agent notification will 404."
    )
    assert "/dashboard/sky-studio?" not in src, (
        "agent_worker regressed to the legacy sky-studio path. That "
        "route was removed in the Phase-2 UI refresh."
    )


def test_comment_service_deep_link_uses_singular_dashboard_route():
    src = inspect.getsource(comment_service)
    assert "/dashboard?id=" in src, (
        "comment_service stopped emitting /dashboard?id=<id> — the "
        "frontend route is singular. Plural /dashboards/<id> silently "
        "navigates nowhere."
    )
    # The old pluralised string must not re-appear in the producer.
    # (String match in source — catches both hand-edits and AI reverts.)
    assert '"/dashboards/"' not in src
    assert 'f"/dashboards/{' not in src


def test_comment_service_deep_link_includes_widget_anchor_when_bound():
    """When the comment is anchored to a widget, the deep_link must
    carry `insight=<widget_id>` so the dashboard page's scroll-to-
    widget handler (Phase 3.4) highlights it."""
    src = inspect.getsource(comment_service)
    assert "insight=" in src, (
        "comment_service no longer adds the insight=<widget_id> "
        "anchor — the Phase-3.4 widget highlight won't trigger on "
        "click-through."
    )
