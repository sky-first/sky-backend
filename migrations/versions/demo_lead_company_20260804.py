"""Empresa e cargo no lead da demo.

Um email sozinho obriga a chegar à reunião a perguntar o básico —
"então, o que é que vocês fazem?" — e gasta nisso os primeiros minutos
dos trinta. Com a empresa e o cargo dá para preparar: ver o site, saber
se se está a falar com quem decide, e entrar já no assunto.

**Ambos opcionais, e é uma decisão e não um esquecimento.** O passo
onde isto vive é o último de um fluxo em que o visitante já deu tempo;
cada campo obrigatório a mais ali é uma razão a mais para fechar o
separador. Quem quiser escrever escreve.

Revision ID: demo_lead_company_20260804
Revises: demo_qa_tiles_20260804
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision = "demo_lead_company_20260804"
down_revision = "demo_qa_tiles_20260804"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("demo_leads", sa.Column("company", sa.String(160), nullable=True))
    op.add_column("demo_leads", sa.Column("role", sa.String(120), nullable=True))


def downgrade() -> None:
    op.drop_column("demo_leads", "role")
    op.drop_column("demo_leads", "company")
