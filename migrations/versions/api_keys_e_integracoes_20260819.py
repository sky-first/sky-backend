"""As tabelas `api_keys` e `integrations` nunca foram criadas.

Encontrado a varrer as leituras em produção com as três contas de teste:

    GET /api/v1/settings/api-keys      -> 500  (owner, admin e member)
    GET /api/v1/settings/integrations  -> 500  (owner, admin e member)

Os modelos existem em ``src/models/permission.py`` desde sempre, as rotas
existem, o serviço existe — só a migração que cria as tabelas é que nunca foi
escrita. Comparando os 84 ``__tablename__`` dos modelos com todos os
``create_table`` das migrações, estas duas eram as únicas em falta que estão
mesmo a ser lidas por uma rota.

Ou seja: dois ecrãs das Definições estão em erro para toda a gente, desde
sempre, escondidos atrás do mesmo 500 genérico que escondia o ``embeddings``.

``checkfirst=True``: em bases onde alguém já as tenha criado à mão, isto não
rebenta. O ``downgrade`` também não apaga dados de bases onde as tabelas já
existiam antes — só desfaz o que este ficheiro criou.

Revision ID: api_keys_e_integracoes_20260819
Revises: cross_project_20260818
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "api_keys_e_integracoes_20260819"
down_revision = "cross_project_20260818"
branch_labels = None
depends_on = None


def upgrade() -> None:
    ligacao = op.get_bind()
    inspector = sa.inspect(ligacao)
    existentes = set(inspector.get_table_names())

    if "api_keys" not in existentes:
        op.create_table(
            "api_keys",
            sa.Column(
                "id",
                postgresql.UUID(as_uuid=True),
                primary_key=True,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("name", sa.String(255), nullable=False),
            # Guardamos o *hash*, nunca a chave. O prefixo é só o que se mostra
            # na lista para a pessoa reconhecer qual é qual.
            sa.Column("key_hash", sa.String(255), nullable=False, unique=True),
            sa.Column("key_prefix", sa.String(20), nullable=False),
            sa.Column("permissions", postgresql.JSON(), nullable=True),
            sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        )
        op.create_index("idx_api_keys_user_id", "api_keys", ["user_id"])
        op.create_index("idx_api_keys_key_hash", "api_keys", ["key_hash"])
        op.create_index("idx_api_keys_expires_at", "api_keys", ["expires_at"])

    if "integrations" not in existentes:
        op.create_table(
            "integrations",
            sa.Column(
                "id",
                postgresql.UUID(as_uuid=True),
                primary_key=True,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("type", sa.String(100), nullable=False),
            sa.Column("config", postgresql.JSON(), nullable=False),
            # `enabled` é String no modelo, não Boolean. Mantém-se assim de
            # propósito: mudar o tipo aqui e deixar o modelo como está trocava
            # um ecrã partido por um erro de serialização.
            sa.Column(
                "enabled",
                sa.String(10),
                nullable=False,
                server_default="true",
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        )
        op.create_index("idx_integrations_user_id", "integrations", ["user_id"])
        op.create_index("idx_integrations_type", "integrations", ["type"])


def downgrade() -> None:
    op.drop_table("integrations")
    op.drop_table("api_keys")
