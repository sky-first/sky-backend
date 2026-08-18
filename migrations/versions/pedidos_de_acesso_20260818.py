"""Quem aprova os dados, e o pedido de quem não os tem.

Duas coisas que o modelo novo obriga (ver
``docs/modelo-projeto-equipa-e-pedidos-de-acesso.md``):

**Quem aprova.** Uma ligação tinha quem a criou e mais nada. Sem alguém
responsável por ela, um pedido de acesso não tem para onde ir. A coluna aponta
ao admin do cliente por omissão (fica nula e o serviço resolve), mas existe
**por ligação** desde já — num cliente de 200 pessoas e 40 fontes um aprovador
central vira gargalo e começa a carimbar sem ler, que é pior do que não ter
processo. Assim a mudança é configuração, não migração.

**O pedido.** Quem cria um projeto começa sem dados e não pode ver o catálogo
para saber o que pedir — ver que uma tabela existe é já informação que a
permissão devia esconder. Então pede em linguagem natural, e a tradução para
tabelas concretas acontece **do lado de quem aprova**. O texto original fica
guardado ao lado da proposta, para o aprovador julgar o que a pessoa pediu e não
o que a máquina entendeu.

O prazo não é opcional de propósito: uma permissão sem fim acumula-se para
sempre e limita o estrago de uma aprovação distraída.

Aditiva: nenhuma linha existente muda, e a reversão é uma queda de tabela mais
uma queda de coluna.

Revision ID: pedidos_de_acesso_20260818
Revises: message_finding_20260814
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "pedidos_de_acesso_20260818"
down_revision = "message_finding_20260814"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "data_connections",
        sa.Column("data_owner_user_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_data_connections_data_owner",
        "data_connections",
        "users",
        ["data_owner_user_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_table(
        "data_access_requests",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "requester_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # O projeto para onde o acesso é pedido. Aprovar um pedido é dar dados
        # a um PROJETO, nunca a uma pessoa solta — é o modelo.
        sa.Column(
            "space_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("spaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("texto", sa.Text(), nullable=False),
        # pending → proposed → approved | rejected ; expired é terminal.
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        # A proposta da IA: [{connection_id, schema_name, table_name, motivo}].
        # Estrutura fechada de propósito — o texto de quem pede entra como
        # dado, nunca como instrução, e a saída não é texto livre.
        sa.Column("proposta", postgresql.JSONB(), nullable=True),
        sa.Column("decided_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("motivo_decisao", sa.Text(), nullable=True),
        # Prazo da permissão concedida. Obrigatório ao aprovar.
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    # Serve as duas leituras que existem: a caixa de quem aprova (por estado) e
    # o travão de quantos pedidos uma pessoa faz por dia.
    op.create_index(
        "idx_data_access_requests_status", "data_access_requests", ["status", "created_at"]
    )
    op.create_index(
        "idx_data_access_requests_requester",
        "data_access_requests",
        ["requester_user_id", "created_at"],
    )
    op.create_index("idx_data_access_requests_space", "data_access_requests", ["space_id"])


def downgrade() -> None:
    op.drop_index("idx_data_access_requests_space", table_name="data_access_requests")
    op.drop_index("idx_data_access_requests_requester", table_name="data_access_requests")
    op.drop_index("idx_data_access_requests_status", table_name="data_access_requests")
    op.drop_table("data_access_requests")
    op.drop_constraint("fk_data_connections_data_owner", "data_connections", type_="foreignkey")
    op.drop_column("data_connections", "data_owner_user_id")
