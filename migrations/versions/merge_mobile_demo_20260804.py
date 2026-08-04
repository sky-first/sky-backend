"""Junta as duas linhas de migração — mobile (BE-01..BE-08) e demo (BE-12).

Os dois trabalhos partiram do mesmo pai, ``seed_gbt_demo_usage_20260624``,
sem se cruzarem:

    seed_gbt_demo_usage_20260624
      ├── tenant_membership_20260730 → … → refresh_token_family_20260730   (mobile)
      └── demo_content_20260803 ────────→ demo_leads_20260803              (demo)

Com duas cabeças, ``alembic upgrade head`` recusa-se a correr — não por
conflito de esquema (as tabelas dos dois lados não se tocam), mas porque
o Alembic não escolhe por nós qual é o estado final. Esta revisão diz
que é a soma dos dois.

Não tem ``upgrade``/``downgrade``: uma migração de junção existe apenas
para reconciliar o grafo. Qualquer DDL aqui seria invisível a quem lesse
os dois ramos em separado.

A causa, para não se repetir: dois ramos longos vivos ao mesmo tempo,
ambos a acrescentar migrações. Quem abrir o segundo ramo deve rebasear
em cima do primeiro ou contar com esta junção — e é mais barato lembrar
antes do que reconciliar depois.
"""

from __future__ import annotations

revision = "merge_mobile_demo_20260804"
down_revision = ("refresh_token_family_20260730", "demo_leads_20260803")
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Sem operações — ver o módulo."""


def downgrade() -> None:
    """Sem operações — desfazer a junção é voltar a ter duas cabeças."""
