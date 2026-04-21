"""Glossary endpoints — /api/v1/glossary.

Terms are bound to the active (space_id, crew_id) context passed as
query params. The AI service indexes them via the standard
``context_documents`` pipeline.
"""

from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_current_user, get_db
from src.models.user import User
from src.schemas.glossary import (
    GlossaryTermCreate,
    GlossaryTermResponse,
    GlossaryTermUpdate,
)
from src.services.glossary_service import GlossaryService
from src.services.rbac_service import RBACService

router = APIRouter()


async def get_glossary_service(
    db: AsyncSession = Depends(get_db),
) -> GlossaryService:
    return GlossaryService(db)


@router.get("/", response_model=List[GlossaryTermResponse])
async def list_glossary(
    space_id: Optional[UUID] = Query(None),
    crew_id: Optional[UUID] = Query(None),
    mine: bool = Query(False, description="Only list terms owned by the caller (personal scope)."),
    current_user: User = Depends(get_current_user),
    service: GlossaryService = Depends(get_glossary_service),
    db: AsyncSession = Depends(get_db),
):
    await RBACService(db).assert_permission(current_user, "strategy.view")
    return await service.list_terms(
        space_id=space_id,
        crew_id=crew_id,
        owner_user_id=current_user.id if mine else None,
    )


@router.post("/", response_model=GlossaryTermResponse, status_code=status.HTTP_201_CREATED)
async def create_glossary(
    payload: GlossaryTermCreate,
    space_id: Optional[UUID] = Query(None),
    crew_id: Optional[UUID] = Query(None),
    current_user: User = Depends(get_current_user),
    service: GlossaryService = Depends(get_glossary_service),
    db: AsyncSession = Depends(get_db),
):
    await RBACService(db).assert_permission(current_user, "strategy.pillars.edit")
    return await service.create_term(
        payload,
        space_id=space_id,
        crew_id=crew_id,
        owner_user_id=current_user.id,
    )


@router.get("/{term_id}", response_model=GlossaryTermResponse)
async def get_glossary_term(
    term_id: UUID,
    space_id: Optional[UUID] = Query(None),
    crew_id: Optional[UUID] = Query(None),
    current_user: User = Depends(get_current_user),
    service: GlossaryService = Depends(get_glossary_service),
    db: AsyncSession = Depends(get_db),
):
    await RBACService(db).assert_permission(current_user, "strategy.view")
    return await service.get_term(term_id, space_id=space_id, crew_id=crew_id)


@router.put("/{term_id}", response_model=GlossaryTermResponse)
async def update_glossary_term(
    term_id: UUID,
    payload: GlossaryTermUpdate,
    space_id: Optional[UUID] = Query(None),
    crew_id: Optional[UUID] = Query(None),
    current_user: User = Depends(get_current_user),
    service: GlossaryService = Depends(get_glossary_service),
    db: AsyncSession = Depends(get_db),
):
    await RBACService(db).assert_permission(current_user, "strategy.pillars.edit")
    return await service.update_term(term_id, payload, space_id=space_id, crew_id=crew_id)


@router.delete("/{term_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_glossary_term(
    term_id: UUID,
    space_id: Optional[UUID] = Query(None),
    crew_id: Optional[UUID] = Query(None),
    current_user: User = Depends(get_current_user),
    service: GlossaryService = Depends(get_glossary_service),
    db: AsyncSession = Depends(get_db),
):
    await RBACService(db).assert_permission(current_user, "strategy.pillars.edit")
    await service.delete_term(term_id, space_id=space_id, crew_id=crew_id)
    return None
