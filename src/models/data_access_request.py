"""O pedido de acesso a dados — de quem não pode ver o catálogo.

Quem cria um projeto começa sem dados nenhuns. Para pedir os que precisa teria
de saber o que existe, e saber o que existe é já informação que a permissão
devia estar a esconder: foi por isso que o Unity Catalog teve de inventar um
privilégio ``BROWSE`` à parte, e é por isso que o *Request for Access* deles
exige esse privilégio ou o URL directo — não resolveram o caso de quem não pode
ver nada.

Aqui pede-se em português: *"preciso dos valores das vendas de 2025"*. A
tradução para tabelas concretas corre **do lado de quem aprova**, e o texto
original fica guardado ao lado da proposta para o aprovador julgar o que a
pessoa pediu, e não o que a máquina entendeu.

Ver ``docs/modelo-projeto-equipa-e-pedidos-de-acesso.md`` §3 e §6.
"""

from __future__ import annotations

import uuid

from sqlalchemy import Column, DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.types import JSON

from src.config.database import Base

# SQLite nos testes não conhece JSONB.
_JSONB_OR_JSON = JSONB().with_variant(JSON(), "sqlite")


#: Um pedido nasce ``pending``, ganha proposta (``proposed``) e acaba
#: ``approved`` ou ``rejected``. ``expired`` é o que o prazo faz à permissão.
ESTADOS = ("pending", "proposed", "approved", "rejected", "expired")


class DataAccessRequest(Base):
    """Um pedido de dados para um projeto."""

    __tablename__ = "data_access_requests"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    requester_user_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    #: Aprovar um pedido é dar dados a um PROJETO, nunca a uma pessoa solta.
    space_id = Column(
        UUID(as_uuid=True), ForeignKey("spaces.id", ondelete="CASCADE"), nullable=False
    )

    texto = Column(Text, nullable=False)
    status = Column(String(20), nullable=False, default="pending", server_default="pending")

    #: ``[{connection_id, schema_name, table_name, motivo}]`` — estrutura
    #: fechada de propósito: o texto de quem pede entra como dado, nunca como
    #: instrução, e a saída da IA não é texto livre que o aprovador leia como
    #: se fosse recomendação.
    proposta = Column(_JSONB_OR_JSON, nullable=True)

    decided_by_user_id = Column(UUID(as_uuid=True), nullable=True)
    decided_at = Column(DateTime(timezone=True), nullable=True)
    motivo_decisao = Column(Text, nullable=True)

    #: Prazo da permissão concedida. Obrigatório ao aprovar — acesso sem fim
    #: acumula-se para sempre e ninguém volta a olhar para ele.
    expires_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index("idx_data_access_requests_status", "status", "created_at"),
        Index("idx_data_access_requests_requester", "requester_user_id", "created_at"),
        Index("idx_data_access_requests_space", "space_id"),
    )

    def __repr__(self) -> str:
        return f"<DataAccessRequest(space_id={self.space_id}, status={self.status})>"
