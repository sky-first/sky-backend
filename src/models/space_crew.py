"""A ligação entre uma equipa e um projeto — com o papel que ela lá tem.

A peça que faltava ao modelo, e que o Jira, o Confluence e o Miro todos têm:
**convidar uma equipa não é convidar e pronto — é convidar COMO alguma coisa.**
A mesma "Comercial" é leitora num projeto e editora noutro.

Ver ``docs/pessoas-equipas-e-projetos.md`` §4.1.

Substitui a cópia de pessoas que se implementou a 25/08: copiar resolvia a
armadilha do S6 destruindo a razão de a equipa existir — acrescentar alguém à
Comercial não o metia nos projetos onde a Comercial trabalha. A ligação é
viva, e a armadilha resolve-se mostrando a proveniência ("via equipa
Comercial"), que é o que os outros fazem.
"""

import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Index, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from src.config.database import Base


class SpaceCrew(Base):
    """Uma equipa com acesso a um projeto."""

    __tablename__ = "space_crews"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    space_id = Column(
        UUID(as_uuid=True), ForeignKey("spaces.id", ondelete="CASCADE"), nullable=False
    )
    crew_id = Column(
        UUID(as_uuid=True), ForeignKey("crews.id", ondelete="CASCADE"), nullable=False
    )
    #: `owner` | `editor` | `viewer` — o MESMO vocabulário do projeto e da
    #: equipa. Antes havia dois (o projeto sem `viewer`), e ninguém sabia
    #: explicar a diferença porque não havia nenhuma.
    role = Column(String(20), nullable=False, default="editor")
    #: Quem convidou. Um convite em massa sem autor é um acesso que ninguém
    #: sabe explicar daqui a três meses.
    added_by = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=datetime.utcnow,
    )

    space = relationship("Space", backref="space_crews")
    crew = relationship("Crew", backref="space_links")

    __table_args__ = (
        # A mesma equipa não entra duas vezes no mesmo projeto. Sem isto,
        # convidar duas vezes daria duas linhas com papéis diferentes e a
        # resolução de acesso passaria a depender da ordem das linhas.
        UniqueConstraint("space_id", "crew_id", name="uq_space_crews_space_crew"),
        Index("idx_space_crews_space", "space_id"),
        Index("idx_space_crews_crew", "crew_id"),
    )

    def __repr__(self) -> str:
        return f"<SpaceCrew(space={self.space_id}, crew={self.crew_id}, role={self.role})>"
