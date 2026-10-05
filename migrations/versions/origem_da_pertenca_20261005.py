"""De onde veio a pertença a um projecto.

`space_members.origem`: `convite` (alguém adicionou) ou `auto_demo` (a
pessoa aderiu sozinha pelo interruptor das definições).

A distinção existe para o desligar do interruptor poder remover só o que
ele próprio criou. Sem ela, desligá-lo tirava também o acesso a quem
tivesse sido **convidado** para um projecto de demonstração — ver
`docs/quem-ve-que-projectos.md`, caso de stress 7.

Tudo o que já existe fica `convite`, que é o que de facto era: ninguém
aderiu sozinho antes desta coluna existir.

Revision ID: origem_pertenca_20261005
Revises: demo_vertical_food_20261003
Create Date: 2026-10-05
"""

from alembic import op
import sqlalchemy as sa

revision = "origem_pertenca_20261005"
down_revision = "demo_vertical_food_20261003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "space_members",
        sa.Column(
            "origem",
            sa.String(length=20),
            nullable=False,
            server_default="convite",
        ),
    )


def downgrade() -> None:
    op.drop_column("space_members", "origem")
