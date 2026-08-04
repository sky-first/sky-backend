"""Conteúdo curado da demo pública — BE-12.

A demo tinha o LLM no caminho crítico do primeiro contacto e falhava com
timeout: medido em produção a 2026-08-03, uma pergunta real leva ~13,7s
contra um limite de 120s no frontend, e antes disso chegava a estourar.
Uma demo comercial não pode ter latência variável de dezenas de segundos
entre o clique no anúncio e o primeiro número no ecrã.

A saída é inverter a natureza do conteúdo: em vez de gerar em runtime,
**curar offline e servir estático**. O agente corre sobre os datasets
sintéticos, escolhem-se os melhores resultados à mão, e persistem-se
aqui. O caminho crítico deixa de tocar no LLM — e por isso deixa de
poder falhar.

Três tabelas:

* ``demo_dataset``  — que dataset serve cada vertical
* ``demo_insight``  — o bloco herói do primeiro ecrã (FE-02)
* ``demo_qa``       — as respostas instantâneas às perguntas sugeridas
                      (FE-03), mais o embedding para o fallback semântico
                      de perguntas livres

Regra editorial, e não é decorativa: **nenhum insight e nenhuma pergunta
pode ser sobre metadados**. Contagens de linhas, tabelas mais usadas e
resumos de esquema ficam de fora — foi exactamente esse tipo de pergunta
("resumo de alto nível — contagem de linhas e tabelas mais usadas") que
arruinou a primeira impressão da demo antiga. Tudo aqui responde a uma
pergunta que um COO faria em voz alta.
"""

from __future__ import annotations

import uuid

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship
from sqlalchemy.types import JSON
from sqlalchemy.types import Text as SAText

from src.config.database import Base

# Shims para o SQLite dos testes. O mesmo padrão de models/agent.py: em
# Postgres usa-se o tipo nativo, em SQLite a alternativa mais próxima.
# Sem isto a tabela nem chega a ser criada em teste.
_JSONB_OR_JSON = JSONB().with_variant(JSON(), "sqlite")

# Tem de bater com a coluna pgvector que o serviço de AI já usa. A
# migração 005 do sky-poc-ai levou todas as colunas de vector para 1024,
# e o provider activo (intfloat/multilingual-e5-large, local) devolve
# 1024. Declarar outra largura aqui faz o INSERT falhar em runtime.
#
# Nota: a spec original dizia 1536 — valor da OpenAI text-embedding-3,
# que não é o provider em uso. Ver src/models/knowledge.py, que ainda
# declara 768 e está desalinhado da coluna real.
EMBEDDING_DIM = 1024

# Os quatro sectores que a demo oferece no passo 1, mais o de omissão.
# "industry" faltava aqui e o passo 1 já o mostrava — quem o escolhesse
# caía no dataset de omissão e recebia perguntas de outro negócio.
VERTICALS = ("saas", "distribution", "services", "industry", "default")


class DemoDataset(Base):
    """Um dataset sintético por vertical, escolhido no primeiro clique."""

    __tablename__ = "demo_datasets"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    vertical = Column(String(32), nullable=False)
    name = Column(String(120), nullable=False)
    description = Column(Text, nullable=True)
    # Referência à connection sintética já existente. Não é FK: o
    # conteúdo curado sobrevive a uma connection ser recriada, e a demo
    # não deve deixar de servir por causa disso.
    connection_ref = Column(String(255), nullable=True)
    # Exactamente um dataset por locale tem de ser o de omissão — é para
    # onde vai quem carrega em "Saltar". Sem ele, saltar seria um beco.
    is_default = Column(Boolean, nullable=False, default=False)
    locale = Column(String(10), nullable=False, default="en")

    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    insights = relationship("DemoInsight", back_populates="dataset", cascade="all, delete-orphan")
    qas = relationship("DemoQA", back_populates="dataset", cascade="all, delete-orphan")

    __table_args__ = (
        CheckConstraint(
            "vertical IN ('saas','distribution','services','default')",
            name="demo_datasets_vertical_check",
        ),
        UniqueConstraint("vertical", "locale", name="uq_demo_datasets_vertical_locale"),
        Index("idx_demo_datasets_lookup", "vertical", "locale"),
        # Um só default por locale, garantido pela base e não pela
        # aplicação — dois defaults tornariam a entrada não-determinista.
        #
        # O predicado tem de ser declarado para os DOIS dialectos: só com
        # ``postgresql_where``, o SQLite ignora-o e cria um índice único
        # sobre `locale` inteiro, o que proíbe dois datasets no mesmo
        # idioma. Apanhado em teste — em Postgres teria passado
        # despercebido até alguém tentar semear duas verticais.
        Index(
            "uq_demo_datasets_one_default_per_locale",
            "locale",
            unique=True,
            postgresql_where=Column("is_default") == True,  # noqa: E712
            sqlite_where=Column("is_default") == True,  # noqa: E712
        ),
    )

    def __repr__(self) -> str:
        return f"<DemoDataset {self.vertical}/{self.locale}>"


class DemoInsight(Base):
    """O bloco herói do primeiro ecrã. Curado, nunca gerado ao vivo."""

    __tablename__ = "demo_insights"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    dataset_id = Column(
        UUID(as_uuid=True),
        ForeignKey("demo_datasets.id", ondelete="CASCADE"),
        nullable=False,
    )

    severity = Column(String(32), nullable=False)
    severity_level = Column(String(16), nullable=False, default="info")
    agent_name = Column(String(120), nullable=False)

    title = Column(Text, nullable=False)
    summary = Column(Text, nullable=False)

    # [{t: ISO-date, v: number}] — a sparkline. Opcional: nem todo o
    # dataset tem série temporal, e o layout não pode partir sem ela.
    series = Column(_JSONB_OR_JSON, nullable=True)
    # [{label, value}], até 3. São os números grandes.
    stat_tiles = Column(_JSONB_OR_JSON, nullable=False, default=list)
    # [{table, description}] — as fontes à vista, que é o que separa
    # isto de um gerador de texto.
    sources = Column(_JSONB_OR_JSON, nullable=False, default=list)
    # O SQL por trás do "ver o SQL". É o elemento de prova mais barato e
    # mais convincente do ecrã.
    executed_sql = Column(Text, nullable=True)

    position = Column(SmallInteger, nullable=False, default=0)

    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    dataset = relationship("DemoDataset", back_populates="insights")

    __table_args__ = (Index("idx_demo_insights_dataset", "dataset_id", "position"),)

    def __repr__(self) -> str:
        return f"<DemoInsight {self.title[:40]!r}>"


class DemoQA(Base):
    """Pergunta sugerida com resposta já calculada.

    O ``embedding`` serve o fallback de ``POST /demo/ask``: quando a
    pergunta livre do visitante excede o limite de tempo, devolve-se a
    QA semanticamente mais próxima em vez de um ecrã de erro. Tem de ser
    produzido pelo **mesmo** provider que embeba a pergunta do visitante
    — mesma largura mas modelo diferente vive noutro espaço vectorial e
    devolve o vizinho errado, em silêncio e sem erro.
    """

    __tablename__ = "demo_qas"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    dataset_id = Column(
        UUID(as_uuid=True),
        ForeignKey("demo_datasets.id", ondelete="CASCADE"),
        nullable=False,
    )

    question = Column(Text, nullable=False)
    answer_markdown = Column(Text, nullable=False)
    citations = Column(_JSONB_OR_JSON, nullable=False, default=list)
    # Os números da resposta, calculados contra os dados sintéticos na
    # curadoria. Sem eles a resposta descreve a análise em vez de a
    # mostrar — e uma demo que fala sobre números sem os apresentar
    # perde exactamente o argumento que estava a tentar fazer.
    stat_tiles = Column(_JSONB_OR_JSON, nullable=False, default=list)
    chart_spec = Column(_JSONB_OR_JSON, nullable=True)
    executed_sql = Column(Text, nullable=True)

    # Só as primeiras N (por position) são mostradas como sugestões; as
    # restantes existem apenas como alvos de fallback.
    position = Column(SmallInteger, nullable=False, default=0)
    is_suggested = Column(Boolean, nullable=False, default=True)

    # O pgvector não existe em SQLite; a variante guarda como texto para
    # a tabela poder ser criada em teste. A pesquisa vectorial só corre
    # em Postgres, que é onde importa.
    embedding = Column(Vector(EMBEDDING_DIM).with_variant(SAText(), "sqlite"), nullable=True)

    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    dataset = relationship("DemoDataset", back_populates="qas")

    __table_args__ = (
        Index("idx_demo_qas_dataset", "dataset_id", "position"),
        Index(
            "idx_demo_qas_suggested",
            "dataset_id",
            "position",
            postgresql_where=Column("is_suggested") == True,  # noqa: E712
        ),
    )

    def __repr__(self) -> str:
        return f"<DemoQA {self.question[:40]!r}>"


class DemoLead(Base):
    """Contacto deixado depois de o visitante ver valor.

    Deliberadamente **sem verificação**: sem bloqueio de domínios e sem
    nada obrigatório além do email. O filtro de "throwaway providers" da demo
    antiga barrava clientes reais que usam gmail como email de empresa —
    um falso positivo caro num formulário de captura.

    Não verificar aqui é seguro porque **nada é provisionado neste
    momento**: até o visitante carregar dados próprios, tudo o que ele vê
    é conteúdo estático curado. Não há sandbox, não há base de dados, não
    há custo. Um email falso custa um lead mau, não recursos.

    A verificação (magic link) pertence ao passo seguinte — o
    provisionamento — que é onde há custo real. Ver BE-10.
    """

    __tablename__ = "demo_leads"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String(320), nullable=False)
    dataset_id = Column(
        UUID(as_uuid=True),
        ForeignKey("demo_datasets.id", ondelete="SET NULL"),
        nullable=True,
    )
    # As perguntas que ele clicou antes de deixar o contacto. É o sinal
    # comercial mais valioso da sessão: diz o que lhe interessou.
    questions_asked = Column(_JSONB_OR_JSON, nullable=False, default=list)
    # Empresa e cargo: o que permite preparar a reunião em vez de a
    # gastar a perguntar o básico. Opcionais de propósito — este é o
    # último ecrã de um fluxo em que ele já deu tempo, e cada campo
    # obrigatório a mais é uma razão a mais para fechar o separador.
    name = Column(String(160), nullable=True)
    company = Column(String(160), nullable=True)
    role = Column(String(120), nullable=True)
    # Até onde ele chegou no fluxo. É o que transforma um contacto numa
    # lista de recuperação: quem ficou no passo 2 não precisa do mesmo
    # email que quem chegou ao calendário e não marcou.
    last_step = Column(Integer, nullable=True)
    vertical = Column(String(32), nullable=True)
    locale = Column(String(10), nullable=True)
    source = Column(String(64), nullable=True)

    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        # Idempotente por email: submeter duas vezes actualiza em vez de
        # duplicar. Um lead por pessoa, não um por clique.
        UniqueConstraint("email", name="uq_demo_leads_email"),
        Index("idx_demo_leads_created", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<DemoLead {self.email}>"


class DemoEvent(Base):
    """Um passo de uma visita à demo. **Sem dados pessoais.**

    Existe porque só se sabia quem chegava ao fim: quem saía a meio era
    invisível, e portanto o passo que perde gente também era.

    A alternativa considerada foi pedir nome e email no primeiro ecrã.
    Media o mesmo e mais — permitia contactar quem desistiu — mas custa
    conversões: este fluxo assenta em dar antes de pedir, e um
    formulário à entrada é o imposto que faz sair quem ainda não viu
    nada. Medir primeiro, decidir depois com números.

    ``session_id`` é gerado no browser e não identifica ninguém. Sem IP,
    sem user agent, sem nada que precise de consentimento.
    """

    __tablename__ = "demo_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column(String(64), nullable=False)
    step = Column(Integer, nullable=False)
    action = Column(String(32), nullable=False)
    vertical = Column(String(32), nullable=True)
    locale = Column(String(10), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        Index("idx_demo_events_session", "session_id"),
        Index("idx_demo_events_created", "created_at"),
        Index("idx_demo_events_step", "step", "action"),
    )

    def __repr__(self) -> str:
        return f"<DemoEvent {self.step}/{self.action}>"


__all__ = [
    "DemoEvent",
    "EMBEDDING_DIM",
    "VERTICALS",
    "DemoDataset",
    "DemoInsight",
    "DemoLead",
    "DemoQA",
]
