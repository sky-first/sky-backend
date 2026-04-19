"""Glossary-term service — thin CRUD bound to the active context.

Terms are always scoped to a (space_id, crew_id) pair inferred from the
request (the caller resolves the active context and hands it in). The
context-event emitter registered for ``GlossaryTerm`` then projects
each mutation into ``context_documents`` automatically.
"""

from typing import List, Optional
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.repositories.glossary import GlossaryTermRepository
from src.schemas.glossary import (
    GlossaryTermCreate,
    GlossaryTermResponse,
    GlossaryTermUpdate,
)


class GlossaryService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = GlossaryTermRepository(db)

    async def list_terms(
        self,
        *,
        space_id: Optional[UUID] = None,
        crew_id: Optional[UUID] = None,
        owner_user_id: Optional[UUID] = None,
    ) -> List[GlossaryTermResponse]:
        filters = {}
        if space_id:
            filters["space_id"] = space_id
        if crew_id:
            filters["crew_id"] = crew_id
        if owner_user_id:
            filters["owner_user_id"] = owner_user_id
        return await self.repo.get_all(filters=filters, order_by="term", limit=500)

    async def get_term(
        self,
        term_id: UUID,
        *,
        space_id: Optional[UUID] = None,
        crew_id: Optional[UUID] = None,
    ) -> GlossaryTermResponse:
        term = await self.repo.get_by_id(term_id)
        if (
            term is None
            or (space_id is not None and term.space_id != space_id)
            or (crew_id is not None and term.crew_id != crew_id)
        ):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Glossary term not found"
            )
        return term

    async def create_term(
        self,
        payload: GlossaryTermCreate,
        *,
        space_id: Optional[UUID] = None,
        crew_id: Optional[UUID] = None,
        owner_user_id: Optional[UUID] = None,
    ) -> GlossaryTermResponse:
        data = payload.model_dump()
        data["space_id"] = space_id
        data["crew_id"] = crew_id
        data["owner_user_id"] = owner_user_id
        term = await self.repo.create(**data)
        await self.db.commit()
        await self.db.refresh(term)
        return term

    async def update_term(
        self,
        term_id: UUID,
        payload: GlossaryTermUpdate,
        *,
        space_id: Optional[UUID] = None,
        crew_id: Optional[UUID] = None,
    ) -> GlossaryTermResponse:
        await self.get_term(term_id, space_id=space_id, crew_id=crew_id)
        term = await self.repo.update(term_id, **payload.model_dump(exclude_unset=True))
        if not term:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Glossary term not found"
            )
        await self.db.commit()
        await self.db.refresh(term)
        return term

    async def delete_term(
        self,
        term_id: UUID,
        *,
        space_id: Optional[UUID] = None,
        crew_id: Optional[UUID] = None,
    ) -> None:
        await self.get_term(term_id, space_id=space_id, crew_id=crew_id)
        ok = await self.repo.delete(term_id)
        if not ok:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Glossary term not found"
            )
        await self.db.commit()
