"""O sector 'industry' passa a ser aceite em demo_datasets.

O passo 1 da demo oferece quatro sectores desde o início — SaaS,
Distribuição, Serviços e Indústria — mas a restrição só conhecia três.
Quem escolhesse Indústria caía no dataset de omissão e recebia perguntas
sobre subscrições e lugares, que é o que faz um prospect concluir em dois
segundos que aquilo não é sobre o negócio dele.

A restrição fica: uma vertical escrita à mão com um erro de escrita
criaria um dataset que a demo nunca serviria, e ninguém daria por isso.

Revision ID: demo_vertical_industry_20260804
Revises: demo_lead_company_20260804
"""

from typing import Sequence, Union

from alembic import op

revision = "demo_vertical_industry_20260804"
down_revision = "demo_lead_company_20260804"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_NOME = "demo_datasets_vertical_check"
_ANTIGO = "('saas', 'distribution', 'services', 'default')"
_NOVO = "('saas', 'distribution', 'services', 'industry', 'default')"


def upgrade() -> None:
    op.drop_constraint(_NOME, "demo_datasets", type_="check")
    op.create_check_constraint(_NOME, "demo_datasets", f"vertical IN {_NOVO}")


def downgrade() -> None:
    # Um dataset de indústria já criado impediria a reposição da
    # restrição antiga. Apagá-lo é o comportamento certo: no esquema
    # antigo ele não podia existir.
    op.execute("DELETE FROM demo_datasets WHERE vertical = 'industry'")
    op.drop_constraint(_NOME, "demo_datasets", type_="check")
    op.create_check_constraint(_NOME, "demo_datasets", f"vertical IN {_ANTIGO}")
