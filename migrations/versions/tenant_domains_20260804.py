"""Domínios de email por cliente — descoberta de tenant no mobile.

Na web o cliente vem do sub-domínio. Uma app móvel fala com um host só,
portanto quando alguém escreve email e password o backend não sabe em
que base procurar — os utilizadores vivem em bases separadas por
cliente. O domínio do email resolve isso, à maneira do Entra ID.

A unicidade global de ``domain`` é a garantia que interessa: se o mesmo
domínio pertencesse a dois clientes, a resolução deixava de ser
determinista e alguém entraria na empresa errada. Imposto pela base, não
pela aplicação.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "tenant_domains_20260804"
down_revision = "merge_mobile_demo_20260804"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"
    uuid_type = postgresql.UUID(as_uuid=True) if is_pg else sa.String(36)

    op.create_table(
        "tenant_domains",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("domain", sa.String(253), nullable=False),
        sa.Column(
            "tenant_id",
            uuid_type,
            sa.ForeignKey("tenant_registry.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("domain", name="uq_tenant_domains_domain"),
    )
    op.create_index("idx_tenant_domains_tenant", "tenant_domains", ["tenant_id"])


def downgrade() -> None:
    op.drop_table("tenant_domains")
