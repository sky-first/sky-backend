"""A equipa entra num projeto COM UM PAPEL, e a ligação é viva.

``space_crews`` é a peça que faltava: convidar uma equipa passa a ser
convidá-la **como** leitora, editora ou dona. A mesma equipa é leitora num
projeto e editora noutro — que é o que o Jira, o Confluence e o Miro fazem, e
o que o Lucas descreveu ao dizer *"dentro do projeto eu tenho é que chamar uma
equipa que já existe"*.

Ver ``docs/pessoas-equipas-e-projetos.md`` §4.1.

**E `space_members.role` passa a aceitar `viewer`.** Havia dois vocabulários
para a mesma ideia — o projeto com ``owner|editor``, a equipa com
``owner|editor|viewer`` — e ninguém sabia explicar a diferença. Não há
nenhuma. Nada se converte: as linhas que existem ficam como estão.

A subida **não dá acesso a ninguém**: a tabela nasce vazia. Quem hoje está num
projeto está lá por `space_members`, e continua.

Revision ID: equipa_no_projeto_20260826
Revises: equipa_sem_projeto_20260825
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "equipa_no_projeto_20260826"
down_revision = "equipa_sem_projeto_20260825"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "space_crews",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "space_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("spaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "crew_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("crews.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.String(length=20), nullable=False, server_default="editor"),
        sa.Column(
            "added_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("space_id", "crew_id", name="uq_space_crews_space_crew"),
    )
    op.create_index("idx_space_crews_space", "space_crews", ["space_id"])
    op.create_index("idx_space_crews_crew", "space_crews", ["crew_id"])

    # O projeto ganha o estado de arquivado. Um projeto de teste que não se
    # pode tirar da frente polui a lista para sempre — e apagar é demasiado.
    op.add_column("spaces", sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index(
        "idx_spaces_archived",
        "spaces",
        ["archived_at"],
        postgresql_where=sa.text("archived_at IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("idx_spaces_archived", table_name="spaces")
    op.drop_column("spaces", "archived_at")
    op.drop_index("idx_space_crews_crew", table_name="space_crews")
    op.drop_index("idx_space_crews_space", table_name="space_crews")
    # Destrutivo, e por escrito: as equipas convidadas perdem o acesso que
    # vinha por esta via. Quem tem linha directa em `space_members` fica.
    op.drop_table("space_crews")
