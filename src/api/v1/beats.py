"""Beats — quota / consumption endpoints.

  • GET /me/beats        — caller's own usage (everyone)
  • GET /tenant/beats    — org-wide aggregate (Owner / Admin only)

Both return the same shape (UsageSnapshot.to_dict). The FE topbar
hover card and Settings → Usage page consume them. See
``src/services/beats_service.py`` for the data model.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_current_user, get_db_session
from src.models.user import User
from src.services.beats_service import BeatsService
from src.services.rbac_service import RBACService

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get(
    "/me/beats",
    status_code=status.HTTP_200_OK,
    summary="Get the caller's beat usage for the current plan window",
    description=(
        "Returns the rolling-window usage snapshot for the authenticated "
        "user. Demo accounts use a 7-day window with a 500-beat budget; "
        "paid plans use 30-day rolling windows. The response is what the "
        "topbar TTL/usage hover card and Profile dropdown render."
    ),
)
async def get_my_beats(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    snapshot = await BeatsService(db).usage_window(current_user, scope="user")
    return snapshot.to_dict()


@router.get(
    "/tenant/beats",
    status_code=status.HTTP_200_OK,
    summary="Get the tenant-wide beat usage (Owner / Admin only)",
    description=(
        "Aggregates beat consumption across every user in the tenant for "
        "the current plan window. Gated by `audit.view` so only Platform "
        "Owner / Admin can see the org bill — Member sees only their own "
        "slice via /me/beats."
    ),
)
async def get_tenant_beats(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    # Owner/Admin only. Reusing the audit.view rule because it's the
    # closest existing tenant-admin gate; a dedicated billing.view
    # rule would be cleaner but adds churn for one endpoint.
    await RBACService(db).assert_permission(current_user, "audit.view")

    snapshot = await BeatsService(db).usage_window(current_user, scope="tenant")
    return snapshot.to_dict()
