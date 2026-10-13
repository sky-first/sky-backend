"""Fontes do sistema: o catálogo de dados públicos da Sky e a activação por cliente.

Ver ``docs/contrato-fontes-do-sistema.md``.

Vivem na base da PLATAFORMA. A mesma migração corre nas bases dos clientes
(o esquema é um só), e lá as tabelas ficam vazias: ninguém as lê.

- ``fontes_sistema`` — o catálogo, escrito uma vez pela equipa Sky.
  Tipo ``A`` = conjunto carregado em tabelas na base ``sky_world``;
  tipo ``B`` = API paga ao vivo (TomTom). O tipo B não está implementado
  nesta fase, mas as colunas (``ferramentas``, ``quota_omissao``,
  ``modelo_custo``) já existem para não haver outra migração.
- ``fontes_sistema_cliente`` — o checkbox da Consola, com o estado do
  provisionamento (``a_preparar → pronta | erro``, ``a_desligar →
  desligada``).
"""

from __future__ import annotations

import uuid

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

from src.config.database import Base

_JSONB_OR_JSON = JSONB().with_variant(JSON(), "sqlite")

TIPOS = ("A", "B")
ESTADOS_CATALOGO = ("rascunho", "ativa", "retirada")
ESTADOS_CLIENTE = ("a_preparar", "pronta", "erro", "a_desligar", "desligada")


class FonteSistema(Base):
    """Uma fonte pública que a Sky oferece aos clientes."""

    __tablename__ = "fontes_sistema"

    #: slug estável: ``combustivel_es``, ``feriados_es_pt``, ``tomtom_rotas``…
    id = Column(String(64), primary_key=True)
    #: ``{"pt": …, "es": …, "en": …}``
    nome = Column(_JSONB_OR_JSON, nullable=False)
    descricao = Column(_JSONB_OR_JSON, nullable=True)
    tipo = Column(String(1), nullable=False, default="A", server_default="A")
    estado = Column(String(20), nullable=False, default="rascunho", server_default="rascunho")
    #: A: tabelas do esquema ``mundo`` que a fonte dá.
    tabelas = Column(_JSONB_OR_JSON, nullable=False, default=list, server_default="[]")
    #: A: os ``mundo.fontes.nome`` que alimentam a fonte (frescura).
    nome_carregador = Column(_JSONB_OR_JSON, nullable=False, default=list, server_default="[]")
    #: B: ferramentas do servidor (``rota_camiao``, ``geocodificar``).
    ferramentas = Column(_JSONB_OR_JSON, nullable=False, default=list, server_default="[]")
    licenca = Column(Text, nullable=True)
    atribuicao = Column(_JSONB_OR_JSON, nullable=True)
    uso_comercial = Column(Boolean, nullable=False, default=False, server_default="false")
    #: Cadência esperada, em minutos. ``atrasada`` = agora − dado_de > 2 × cadência.
    cadencia_min = Column(Integer, nullable=True)
    #: ``{"tipo": "fixo"|"por_pedido", "eur_por_1000": …, "gratis_mes": …, "tecto_global_mes": …}``
    modelo_custo = Column(_JSONB_OR_JSON, nullable=True)
    planos_permitidos = Column(
        _JSONB_OR_JSON,
        nullable=False,
        default=lambda: ["starter", "core", "plus", "enterprise"],
        server_default='["starter", "core", "plus", "enterprise"]',
    )
    #: Decisão do Lucas (13/10/2026): as fontes do sistema NÃO contam como
    #: «fonte de dados» do plano.
    conta_como_fonte = Column(Boolean, nullable=False, default=False, server_default="false")
    #: B: pedidos por mês por plano. ``null`` = à medida (Enterprise).
    quota_omissao = Column(_JSONB_OR_JSON, nullable=True)
    versao = Column(Integer, nullable=False, default=1, server_default="1")
    criado_por = Column(String(255), nullable=True)
    criado_em = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    actualizado_em = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        CheckConstraint("tipo IN ('A', 'B')", name="fontes_sistema_tipo_check"),
        CheckConstraint(
            "estado IN ('rascunho', 'ativa', 'retirada')", name="fontes_sistema_estado_check"
        ),
        # Uma fonte sem licença comercial nunca pode estar activa (S8).
        CheckConstraint(
            "estado <> 'ativa' OR uso_comercial", name="fontes_sistema_ativa_exige_comercial"
        ),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<FonteSistema {self.id} {self.tipo} {self.estado}>"


class FonteSistemaCliente(Base):
    """O checkbox de uma fonte num cliente, e onde vai o provisionamento."""

    __tablename__ = "fontes_sistema_cliente"

    tenant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("tenant_registry.id", ondelete="CASCADE"),
        primary_key=True,
    )
    fonte_id = Column(
        String(64),
        ForeignKey("fontes_sistema.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    ativa = Column(Boolean, nullable=False, default=False, server_default="false")
    estado = Column(String(20), nullable=False, default="a_preparar", server_default="a_preparar")
    #: Última falha de provisionamento, sem segredos: ``{"mensagem", "passo", "quando"}``.
    erro = Column(_JSONB_OR_JSON, nullable=True)
    #: B: sobrepõe a quota do plano (plano especial).
    quota_mes = Column(Integer, nullable=True)
    #: Muda a cada PUT da Consola. A tarefa compara-o no fim para convergir
    #: quando dois operadores mexem ao mesmo tempo (S17).
    pedido_id = Column(UUID(as_uuid=True), nullable=False, default=uuid.uuid4)
    ativada_por = Column(String(255), nullable=True)
    ativada_em = Column(DateTime(timezone=True), nullable=True)
    desativada_por = Column(String(255), nullable=True)
    desativada_em = Column(DateTime(timezone=True), nullable=True)
    pronta_em = Column(DateTime(timezone=True), nullable=True)
    actualizado_em = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "estado IN ('a_preparar', 'pronta', 'erro', 'a_desligar', 'desligada')",
            name="fontes_sistema_cliente_estado_check",
        ),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<FonteSistemaCliente {self.tenant_id} {self.fonte_id} {self.ativa} {self.estado}>"
