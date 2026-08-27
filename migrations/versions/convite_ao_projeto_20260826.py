"""Convidar UMA pessoa para um projeto — e ela aceitar.

> *"Enviamos um convite à pessoa, esta recebe uma notificação e aceita o
> projeto, e nós recebemos uma notificação que a pessoa aceitou."* — Lucas

**Porque uma tabela e não acrescentar a pessoa logo.** Porque aceitar tem de
querer dizer alguma coisa. Se convidar já desse acesso, o botão de aceitar era
decoração e o de recusar era uma mentira — a pessoa já lá teria estado dentro,
a ver dados de uma área que talvez não seja a dela.

Enquanto o convite está `pendente` a pessoa **não** alcança o projeto: esta
tabela não é lida por `acesso_ao_projeto`. Ao aceitar, entra pela equipa
**Geral**, como qualquer outra pessoa convidada à unidade.

A subida não dá acesso a ninguém: a tabela nasce vazia.

Revision ID: convite_ao_projeto_20260826
Revises: equipa_no_projeto_20260826
Create Date: 2026-08-26
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "convite_ao_projeto_20260826"
down_revision = "equipa_no_projeto_20260826"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "convites_ao_projeto",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "space_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("spaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("papel", sa.String(20), nullable=False, server_default="editor"),
        sa.Column("estado", sa.String(20), nullable=False, server_default="pendente"),
        sa.Column(
            "convidado_por",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("respondido_em", sa.DateTime(timezone=True), nullable=True),
        # Um convite VIVO de cada vez por pessoa e projeto. O estado entra na
        # chave porque os convites respondidos ficam guardados — quem recusou
        # pode ser convidado outra vez, e a segunda tentativa não pode chocar
        # com o registo da primeira.
        sa.UniqueConstraint("space_id", "user_id", "estado", name="uq_convite_vivo"),
    )
    op.create_index("ix_convites_ao_projeto_space_id", "convites_ao_projeto", ["space_id"])
    op.create_index("ix_convites_ao_projeto_user_id", "convites_ao_projeto", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_convites_ao_projeto_user_id", table_name="convites_ao_projeto")
    op.drop_index("ix_convites_ao_projeto_space_id", table_name="convites_ao_projeto")
    op.drop_table("convites_ao_projeto")
