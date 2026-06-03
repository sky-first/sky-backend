"""Insights Analytics — Owner-only dashboard endpoint.

Returns the aggregated value-meter the customer's finance team
ultimately reads:
  • insights produced (by tier),
  • analyst-hours saved,
  • dollar value relative to a traditional BI flow,
  • cost transparency (tokens + USD), so the ROI multiplier is honest.

Demo accounts hit the same endpoint. They can pass `range=session` to
get a window of "last 24h" — the FE Settings page picks the default
range based on whether the caller is on a demo plan.

Gating: Owner-only. Admins see the same data via /tenant/beats; this
endpoint is the *value-framed* counterpart, intentionally only
exposed to the org's tomador-de-decisão.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_current_user, get_db_session
from src.models.user import User
from src.services.insights_analytics_service import (
    InsightsAnalyticsService,
    Range,
)

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get(
    "/me/insights-analytics",
    status_code=status.HTTP_200_OK,
    summary="Insights-Analytics dashboard snapshot (Owner-only)",
    description=(
        "Aggregated insights production over a configurable range. "
        "Owner-only — surfaces tenant-wide spend, hours saved, and ROI, "
        "which is decision-maker territory. Members get 403 here and "
        "should consume /me/beats for their personal usage instead."
    ),
)
async def get_insights_analytics(
    range_: Range = Query(
        "quarter",
        alias="range",
        description=(
            "Aggregation window. `session` gives last-24h "
            "(demo-friendly); `month` / `quarter` / `year` are "
            "calendar-aligned; `today` resets each midnight; "
            "`all` includes every row."
        ),
    ),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    # Owner-only — Admins and Members are deliberately excluded.
    # Same gate used by branding.py and tenant_plan.py: this surface
    # carries the upgrade-conversation framing, which is the org's
    # tomador-de-decisão's territory, not the day-to-day operator's.
    if current_user.role not in ("super_admin", "owner"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Insights Analytics is reserved for the platform SuperAdmin. "
                "Use /me/beats for personal usage."
            ),
        )

    try:
        snapshot = await InsightsAnalyticsService(db, user=current_user).snapshot(range_)
    except Exception:
        # Endpoint is new and rendering is best-effort — surface the
        # full stack to the structured logger so we can root-cause in
        # the cluster without inflicting a 500 on the customer. The
        # generic INTERNAL_ERROR envelope is what they'd otherwise see.
        logger.exception(
            "insights_analytics_snapshot_failed user=%s range=%s",
            current_user.id,
            range_,
        )
        raise
    return snapshot.to_dict()
