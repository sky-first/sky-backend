"""Números nas respostas curadas da demo.

As respostas descreviam a análise em vez de a mostrar: *"contas
marcadas como risco, ordenadas pela receita mensal"* é uma frase sobre
uma query, não uma resposta. Um comprador lê aquilo e pergunta "e os
números?" — e tem razão, porque o argumento inteiro da demo é que o
produto devolve factos com fontes à vista.

``stat_tiles`` guarda os valores calculados contra o conjunto sintético
no momento da curadoria, pelo mesmo caminho que já alimenta os cartões
do insight herói: SQL escalar, executado e verificado, nunca escrito à
mão.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "demo_qa_tiles_20260804"
down_revision = "tenant_domains_20260804"
branch_labels = None
depends_on = None


def upgrade() -> None:
    json_type = postgresql.JSONB if op.get_bind().dialect.name == "postgresql" else sa.JSON
    op.add_column(
        "demo_qas",
        sa.Column("stat_tiles", json_type, nullable=False, server_default="[]"),
    )


def downgrade() -> None:
    op.drop_column("demo_qas", "stat_tiles")
