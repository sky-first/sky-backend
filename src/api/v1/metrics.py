"""Metric endpoints — /api/v1/metrics (Knowledge refactor Phase 2).

Phase 2 ships CRUD + scope-aware listing. Certification and AI rewiring
land in later phases on top of this surface.
"""

from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_current_user, get_db
from src.core.scope_guard import assert_not_personal_scope
from src.models.user import User
from src.schemas.metric import MetricCreate, MetricRead, MetricUpdate
from src.services.metric_service import MetricService
from src.services.rbac_service import RBACService

router = APIRouter()


async def _service(db: AsyncSession = Depends(get_db)) -> MetricService:
    return MetricService(db)


@router.get("/", response_model=List[MetricRead])
async def list_metrics(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    service: MetricService = Depends(_service),
):
    """Return every metric the caller can see across personal/crew/space/org."""
    await RBACService(db).assert_permission(current_user, "connections.view")
    return await service.list_visible(current_user)


@router.post(
    "/",
    response_model=MetricRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_metric(
    payload: MetricCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    service: MetricService = Depends(_service),
):
    assert_not_personal_scope(payload.scope)
    await RBACService(db).assert_permission(current_user, "connections.view")
    metric = await service.create(current_user, payload)
    await db.commit()
    return metric


@router.get("/{metric_id}", response_model=MetricRead)
async def get_metric(
    metric_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    service: MetricService = Depends(_service),
):
    await RBACService(db).assert_permission(current_user, "connections.view")
    return await service.get(current_user, metric_id)


@router.patch("/{metric_id}", response_model=MetricRead)
async def update_metric(
    metric_id: UUID,
    payload: MetricUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    service: MetricService = Depends(_service),
):
    await RBACService(db).assert_permission(current_user, "connections.view")
    metric = await service.update(current_user, metric_id, payload)
    await db.commit()
    return metric


@router.delete("/{metric_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_metric(
    metric_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    service: MetricService = Depends(_service),
):
    await RBACService(db).assert_permission(current_user, "connections.view")
    await service.delete(current_user, metric_id)
    await db.commit()
