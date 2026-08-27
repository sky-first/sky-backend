"""Crew models."""

import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Index, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from src.config.database import Base


class Crew(Base):
    """Crew model."""

    __tablename__ = "crews"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    #: O projeto a que esta equipa pertence — ou ``None``, se for do cliente.
    #:
    #: **Passou a poder ser nulo, e é a mudança que faz a equipa ser gente.**
    #:
    #: Uma equipa nascia sempre dentro de um projeto. Isso obrigava a recriar a
    #: "Equipa Comercial" em cada projeto novo: seis pessoas escritas outra vez,
    #: seis listas que divergem, e acrescentar alguém à empresa não chegava a
    #: lado nenhum. Era o modelo errado, e o Lucas apanhou-o a usar a app —
    #: *"dentro do projeto eu tenho é que chamar uma equipa que já existe"*.
    #:
    #: Com ``None``, a equipa é do cliente: uma **lista de pessoas reutilizável**
    #: (``docs/modelo-projeto-equipa-e-pedidos-de-acesso.md`` §1). Convidá-la
    #: para um projeto **copia** as pessoas — é uma fotografia, não uma ligação
    #: viva. Essa decisão é o S6 do mesmo documento, e existe porque a
    #: alternativa é a armadilha mais provável deste modelo: tirar alguém da
    #: equipa e julgar que se lhe cortou o acesso aos projetos, quando não se
    #: cortou.
    #:
    #: As que já existem ficam como estão (com projeto). Nada se migra à força:
    #: uma equipa presa a um projeto continua a funcionar exactamente como
    #: funcionava.
    space_id = Column(
        UUID(as_uuid=True),
        ForeignKey("spaces.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    created_by = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=datetime.utcnow,
    )
    deleted_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    space = relationship("Space", back_populates="crews")
    members = relationship("CrewMember", back_populates="crew", cascade="all, delete-orphan")
    crew_connections = relationship(
        "CrewConnection", back_populates="crew", cascade="all, delete-orphan"
    )
    crew_tables = relationship("CrewTable", back_populates="crew", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_crews_space_id", "space_id", postgresql_where=deleted_at.is_(None)),
        Index("idx_crews_created_by", "created_by", postgresql_where=deleted_at.is_(None)),
    )

    def __repr__(self) -> str:
        return f"<Crew(id={self.id}, name={self.name}, space_id={self.space_id})>"


class CrewMember(Base):
    """Crew member model."""

    __tablename__ = "crew_members"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    crew_id = Column(
        UUID(as_uuid=True),
        ForeignKey("crews.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role = Column(String(50), nullable=False)  # owner, editor, viewer
    joined_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    # Relationships
    crew = relationship("Crew", back_populates="members")
    user = relationship("User")

    __table_args__ = (
        UniqueConstraint("crew_id", "user_id", name="uq_crew_members_crew_user"),
        Index("idx_crew_members_crew_id", "crew_id"),
        Index("idx_crew_members_user_id", "user_id"),
    )

    def __repr__(self) -> str:
        return f"<CrewMember(crew_id={self.crew_id}, user_id={self.user_id}, role={self.role})>"


class CrewConnection(Base):
    """Crew-Connection association table."""

    __tablename__ = "crew_connections"

    crew_id = Column(
        UUID(as_uuid=True),
        ForeignKey("crews.id", ondelete="CASCADE"),
        primary_key=True,
        index=True,
    )
    connection_id = Column(
        UUID(as_uuid=True),
        ForeignKey("data_connections.id", ondelete="CASCADE"),
        primary_key=True,
        index=True,
    )

    # Relationships
    crew = relationship("Crew", back_populates="crew_connections")
    connection = relationship("DataConnection")

    __table_args__ = (
        Index("idx_crew_connections_crew_id", "crew_id"),
        Index("idx_crew_connections_connection_id", "connection_id"),
    )

    def __repr__(self) -> str:
        return f"<CrewConnection(crew_id={self.crew_id}, connection_id={self.connection_id})>"


class CrewTable(Base):
    """Crew specific table association.

    Mirrors ``SpaceTable`` one level down: a crew is restricted to specific
    tables of a connection it has access to.

    Este texto dizia, até 18/08/2026, que uma equipa com ``CrewConnection`` e
    **sem** linhas aqui herdava todas as tabelas do projeto. Era falso desde a
    reescrita fail-closed: ``PermissionService._get_crew_table_names`` devolve
    lista vazia, e sem concessão não há acesso. O comentário é que estava
    velho — mas um comentário destes lê-se como especificação e mais tarde
    alguém "corrige" o código para o cumprir.

    Nota de rumo: com ``settings.DATA_BOUNDARY == "project"`` esta tabela deixa
    de ser a fronteira de dados (passa a ser ``space_tables``) e a equipa fica a
    ser só gente. Ver ``docs/fronteira-de-dados-projeto.md``.
    """

    __tablename__ = "crew_tables"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    crew_id = Column(
        UUID(as_uuid=True),
        ForeignKey("crews.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    connection_id = Column(
        UUID(as_uuid=True),
        ForeignKey("data_connections.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    table_name = Column(String(255), nullable=False)
    schema_name = Column(String(255), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    # Relationships
    crew = relationship("Crew", back_populates="crew_tables")
    connection = relationship("DataConnection")

    __table_args__ = (
        Index(
            "idx_crew_tables_crew_conn_table",
            "crew_id",
            "connection_id",
            "table_name",
            "schema_name",
            unique=True,
        ),
    )

    def __repr__(self) -> str:
        return f"<CrewTable(crew_id={self.crew_id}, table={self.table_name})>"
