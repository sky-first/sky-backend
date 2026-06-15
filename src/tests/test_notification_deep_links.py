"""Regression pinning for notification deep-link shapes.

User-reported bugs pinned here so future renames break CI, not users:

  * 2026-04-16: Agent notifications linked to /dashboard/sky-studio
    (renamed to /dashboard/universe-intelligence). Clicks 404'd.

  * 2026-04-16: Comment @mention notifications linked to /dashboards/<id>
    (plural). The frontend route is singular (/page?id=<id>).
    Clicks silently went nowhere.

  * 2026-06-15: FE route /dashboard renamed to /page (PR #495).
    next.config.mjs redirects only apply to HTTP — router.push is
    client-side and does not follow them. All deep-link producers
    updated to emit /page?… directly.
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


def test_comment_service_deep_link_uses_page_route():
    """Pins that comment_service emits /page?id=… (not the old /dashboard path).

    FE route was renamed /dashboard → /page in PR #495. router.push does not
    follow next.config.mjs redirects, so stale /dashboard paths silently go
    nowhere on client-side navigation.
    """
    src = inspect.getsource(comment_service)
    assert "/page?id=" in src, (
        "comment_service stopped emitting /page?id=<id> — the "
        "frontend route moved from /dashboard to /page (PR #495). "
        "Revert to /page?id= to fix notification click-through."
    )
    # Guard against regression to old paths.
    assert '"/dashboards/"' not in src, "comment_service regressed to plural /dashboards/"
    assert 'f"/dashboards/{' not in src, "comment_service regressed to plural /dashboards/<id>"
    assert '"/dashboard?id=' not in src, "comment_service regressed to old /dashboard route"


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
