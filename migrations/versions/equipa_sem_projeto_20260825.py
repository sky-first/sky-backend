"""A equipa deixa de ter de pertencer a um projeto.

Uma equipa nascia sempre dentro de um projeto (``crews.space_id NOT NULL``).
Isso obrigava a recriar a "Equipa Comercial" em cada projeto novo: as mesmas
seis pessoas escritas outra vez, seis listas que divergem, e acrescentar
alguém à empresa não chegava a lado nenhum.

Com a coluna a aceitar nulo, uma equipa pode ser **do cliente**: uma lista de
pessoas reutilizável, que se convida para os projetos que se quiser
(``docs/modelo-projeto-equipa-e-pedidos-de-acesso.md`` §1).

**Nada se migra.** As equipas que existem ficam com o seu projeto e continuam a
funcionar exactamente como funcionavam. Esta migração só abre a porta; não
empurra ninguém por ela.

A descida repõe o ``NOT NULL`` — e por isso **apaga** as equipas sem projeto,
que é a única coisa que se pode fazer com elas nesse esquema. Fica escrito
aqui em vez de ser descoberto durante uma reversão.

Revision ID: equipa_sem_projeto_20260825
Revises: api_keys_e_integracoes_20260819
"""

import sqlalchemy as sa
from alembic import op

revision = "equipa_sem_projeto_20260825"
down_revision = "api_keys_e_integracoes_20260819"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "crews",
        "space_id",
        existing_type=sa.dialects.postgresql.UUID(as_uuid=True),
        nullable=True,
    )


def downgrade() -> None:
    # Sem projeto não há linha válida no esquema antigo. Apagar é a única
    # descida possível — e é destrutiva, de propósito e por escrito.
    op.execute("DELETE FROM crews WHERE space_id IS NULL")
    op.alter_column(
        "crews",
        "space_id",
        existing_type=sa.dialects.postgresql.UUID(as_uuid=True),
        nullable=False,
    )
