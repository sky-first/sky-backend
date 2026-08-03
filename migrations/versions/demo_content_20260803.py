"""Conteúdo curado da demo pública — BE-12.

Cria ``demo_datasets``, ``demo_insights`` e ``demo_qas``.

A demo tinha o LLM no caminho crítico do primeiro contacto e falhava com
timeout. Estas tabelas guardam conteúdo **curado offline** — insight
herói e respostas pré-calculadas — para que o primeiro ecrã não dependa
de nenhuma geração em runtime.

Notas de esquema:

* ``demo_qas.embedding`` é ``vector(1024)``, não 1536. Tem de bater com
  a coluna que o serviço de AI já usa (migração 005 do sky-poc-ai levou
  tudo para 1024) e com o provider activo,
  ``intfloat/multilingual-e5-large``. Um valor diferente faz o INSERT
  falhar em runtime.
* A extensão ``vector`` é criada por ``CREATE EXTENSION IF NOT EXISTS``:
  o serviço de AI já a activa, mas esta migração pode correr primeiro
  numa base nova.
* O índice parcial ``uq_demo_datasets_one_default_per_locale`` garante
  na base que há **um só** dataset de omissão por locale. Dois defaults
  tornariam a entrada da demo não-determinista, e validar isso só na
  aplicação deixa a porta aberta.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "demo_content_20260803"
down_revision = "seed_gbt_demo_usage_20260624"
branch_labels = None
depends_on = None

EMBEDDING_DIM = 1024


def _try_enable_vector(bind) -> bool:
    """Activa pgvector, devolvendo se está disponível.

    Produção e staging têm-no (o serviço de AI já o usa), mas o
    `docker-compose` de desenvolvimento corre `postgres:14-alpine`, que
    não traz a extensão. Sem esta salvaguarda a migração rebentava na
    máquina de quem só quer ver a demo a funcionar.

    Sem pgvector cria-se tudo excepto a coluna de embedding, e o
    fallback de ``/demo/ask`` usa a primeira pergunta sugerida em vez da
    semanticamente mais próxima — que é precisamente a degradação que o
    serviço já sabe fazer quando não há embeddings. A demo funciona; só
    o fallback é menos fino.
    """
    try:
        with bind.begin_nested():
            bind.exec_driver_sql("CREATE EXTENSION IF NOT EXISTS vector")
        return True
    except Exception as exc:  # noqa: BLE001
        print(
            f"[demo_content] pgvector indisponível ({exc.__class__.__name__}); "
            "demo_qas fica sem coluna `embedding` e o fallback de /demo/ask "
            "usa a primeira sugerida. Em produção isto NÃO deve acontecer."
        )
        return False


def upgrade() -> None:
    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"

    has_vector = _try_enable_vector(bind) if is_pg else False

    uuid_type = postgresql.UUID(as_uuid=True) if is_pg else sa.String(36)
    json_type = postgresql.JSONB if is_pg else sa.JSON

    op.create_table(
        "demo_datasets",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("vertical", sa.String(32), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("connection_ref", sa.String(255), nullable=True),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("locale", sa.String(10), nullable=False, server_default="en"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "vertical IN ('saas','distribution','services','default')",
            name="demo_datasets_vertical_check",
        ),
        sa.UniqueConstraint("vertical", "locale", name="uq_demo_datasets_vertical_locale"),
    )
    op.create_index("idx_demo_datasets_lookup", "demo_datasets", ["vertical", "locale"])
    # Índice parcial: único apenas entre as linhas com is_default. Sem o
    # predicado seria um único sobre `locale` inteiro, o que proibiria
    # dois datasets no mesmo idioma. Postgres e SQLite suportam ambos
    # índices parciais, com a mesma sintaxe.
    op.execute(
        "CREATE UNIQUE INDEX uq_demo_datasets_one_default_per_locale "
        "ON demo_datasets (locale) WHERE is_default"
    )

    op.create_table(
        "demo_insights",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column(
            "dataset_id",
            uuid_type,
            sa.ForeignKey("demo_datasets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("severity", sa.String(32), nullable=False),
        sa.Column("severity_level", sa.String(16), nullable=False, server_default="info"),
        sa.Column("agent_name", sa.String(120), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("series", json_type, nullable=True),
        sa.Column("stat_tiles", json_type, nullable=False, server_default="[]"),
        sa.Column("sources", json_type, nullable=False, server_default="[]"),
        sa.Column("executed_sql", sa.Text(), nullable=True),
        sa.Column("position", sa.SmallInteger(), nullable=False, server_default="0"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("idx_demo_insights_dataset", "demo_insights", ["dataset_id", "position"])

    op.create_table(
        "demo_qas",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column(
            "dataset_id",
            uuid_type,
            sa.ForeignKey("demo_datasets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("answer_markdown", sa.Text(), nullable=False),
        sa.Column("citations", json_type, nullable=False, server_default="[]"),
        sa.Column("chart_spec", json_type, nullable=True),
        sa.Column("executed_sql", sa.Text(), nullable=True),
        sa.Column("position", sa.SmallInteger(), nullable=False, server_default="0"),
        sa.Column("is_suggested", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("idx_demo_qas_dataset", "demo_qas", ["dataset_id", "position"])

    # A coluna existe SEMPRE, em qualquer dialecto — o modelo declara-a,
    # portanto qualquer `SELECT` sobre demo_qas rebentaria se ela
    # faltasse. Sem pgvector guarda-se como TEXT (a mesma variante que o
    # modelo já usa em SQLite): fica sempre NULL, a pesquisa vectorial
    # nunca corre, e o fallback textual serve na mesma.
    #
    # Criá-la incondicionalmente também impede a migração e o
    # `create_all` dos testes de divergirem — dois caminhos a produzir
    # esquemas diferentes é a espécie de diferença que só aparece em
    # produção.
    col_type = f"vector({EMBEDDING_DIM})" if has_vector else "text"
    op.execute(f"ALTER TABLE demo_qas ADD COLUMN embedding {col_type}")

    if is_pg:
        op.execute(
            "CREATE INDEX idx_demo_qas_suggested ON demo_qas (dataset_id, position) "
            "WHERE is_suggested"
        )


def downgrade() -> None:
    op.drop_table("demo_qas")
    op.drop_table("demo_insights")
    op.drop_table("demo_datasets")
