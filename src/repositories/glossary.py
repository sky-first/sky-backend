"""Glossary-term repository."""

from sqlalchemy.ext.asyncio import AsyncSession

from src.models.glossary import GlossaryTerm
from src.repositories.base import BaseRepository


class GlossaryTermRepository(BaseRepository[GlossaryTerm]):
    def __init__(self, db: AsyncSession):
        super().__init__(db, GlossaryTerm)
