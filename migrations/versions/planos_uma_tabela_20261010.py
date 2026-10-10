"""Os planos passam a uma tabela só — e a bloquear (10/10/2026).

Ver `docs/PLANOS_E_LIMITES_2026-10.md`.

1. Colunas novas em `tenant_plan_limits`: `max_connections`,
   `min_agent_interval_minutes`, `personalizado`.
2. Os nomes dos planos passam a ser os da proposta comercial: starter ·
   core · plus · enterprise. Os antigos mapeiam (foundation → core, scale →
   plus, pilot → starter, advanced/strategic → enterprise).
3. **Onde há `tenant_registry` com clientes** (a base da plataforma), cada
   cliente fica com uma linha com os tectos do plano que está no registo.
   Uma linha que já exista e que não seja «personalizada» é reposta com os
   tectos do plano — as que existiam nasceram «enterprise sem tecto» por
   engano, e era por isso que nenhum cliente tinha limites.

Na base de cada cliente a tabela também existe (o mesmo esquema), e a
migração corre lá igual: inofensivo, porque a partir de agora essas linhas
não são lidas por ninguém.

Revision ID: planos_uma_tabela_20261010
Revises: agente_nao_repete_20261007
Create Date: 2026-10-10
"""

from alembic import op
import sqlalchemy as sa

revision = "planos_uma_tabela_20261010"
down_revision = "agente_nao_repete_20261007"
branch_labels = None
depends_on = None

# Copiado de `src/services/planos.py` de propósito: uma migração não pode
# mudar quando o código muda.
_TECTOS = {
    "starter": (1, 10, 500, 10, 1440),
    "core": (2, 30, 2000, 50, 60),
    "plus": (5, 100, 8000, 200, 15),
    "enterprise": (10, 300, 30000, 500, 5),
}
_ANTIGOS = {
    "pilot": "starter",
    "foundation": "core",
    "scale": "plus",
    "advanced": "enterprise",
    "strategic": "enterprise",
}


def _plano(t):
    t = (t or "").strip().lower()
    t = _ANTIGOS.get(t, t)
    return t if t in _TECTOS else None


def upgrade() -> None:
    bind = op.get_bind()
    tabelas = sa.inspect(bind).get_table_names()
    if "tenant_plan_limits" not in tabelas:
        return

    op.add_column("tenant_plan_limits", sa.Column("max_connections", sa.Integer(), nullable=True))
    op.add_column(
        "tenant_plan_limits",
        sa.Column("min_agent_interval_minutes", sa.Integer(), nullable=True),
    )
    op.add_column(
        "tenant_plan_limits",
        sa.Column("personalizado", sa.Boolean(), nullable=False, server_default="false"),
    )

    if bind.dialect.name == "postgresql":
        op.execute(
            "ALTER TABLE tenant_plan_limits DROP CONSTRAINT IF EXISTS tenant_plan_limits_tier_check"
        )
    for antigo, novo in (("pilot", "starter"), ("foundation", "core"), ("scale", "plus")):
        bind.execute(
            sa.text("UPDATE tenant_plan_limits SET tier = :n WHERE tier = :a"),
            {"n": novo, "a": antigo},
        )
    if bind.dialect.name == "postgresql":
        op.execute(
            "ALTER TABLE tenant_plan_limits ADD CONSTRAINT tenant_plan_limits_tier_check "
            "CHECK (tier IN ('starter', 'core', 'plus', 'enterprise')) NOT VALID"
        )
        op.execute("ALTER TABLE tenant_plan_limits ALTER COLUMN tier SET DEFAULT 'starter'")

    if "tenant_registry" not in tabelas:
        return

    # O registo dos clientes tinha a sua própria lista de planos
    # (starter/foundation/core/advanced/strategic), que nem incluía os
    # nomes que a Consola gravava. Passa aos mesmos quatro. Aqui o «core»
    # ANTIGO era o plano de 1800 € (ver o antigo `tectos_do_plano`), por
    # isso mapeia para plus — e só aqui, uma vez.
    if bind.dialect.name == "postgresql":
        op.execute(
            "ALTER TABLE tenant_registry DROP CONSTRAINT IF EXISTS tenant_registry_tier_check"
        )
    for antigo, novo in (
        ("core", "plus"),
        ("foundation", "core"),
        ("scale", "plus"),
        ("pilot", "starter"),
        ("advanced", "enterprise"),
        ("strategic", "enterprise"),
    ):
        bind.execute(
            sa.text("UPDATE tenant_registry SET tier = :n WHERE tier = :a"),
            {"n": novo, "a": antigo},
        )
    if bind.dialect.name == "postgresql":
        op.execute(
            # NOT VALID: um valor que ninguém conhece (escrito à mão algures)
            # não pode fazer a migração inteira falhar no deploy. O serviço
            # recusa servir esse cliente até a Consola lhe dar um plano.
            "ALTER TABLE tenant_registry ADD CONSTRAINT tenant_registry_tier_check "
            "CHECK (tier IN ('starter', 'core', 'plus', 'enterprise')) NOT VALID"
        )

    clientes = bind.execute(sa.text("SELECT id, tier FROM tenant_registry")).mappings().all()
    for c in clientes:
        plano = _plano(c["tier"])
        if plano is None:
            # Não se inventa: fica sem linha e o serviço recusa (fail-closed)
            # até a Consola escolher um plano. Um plano desconhecido é um erro
            # nosso, e tem de aparecer — não ser «ilimitado».
            continue
        conn, agents, queries, gb, intervalo = _TECTOS[plano]
        existe = bind.execute(
            sa.text("SELECT personalizado FROM tenant_plan_limits WHERE tenant_id = :t"),
            {"t": c["id"]},
        ).first()
        valores = {
            "t": c["id"],
            "tier": plano,
            "conn": conn,
            "agents": agents,
            "queries": queries,
            "gb": gb,
            "intervalo": intervalo,
        }
        if existe is None:
            bind.execute(
                sa.text(
                    "INSERT INTO tenant_plan_limits (tenant_id, tier, max_connections, max_agents, "
                    "max_queries_per_month, max_storage_gb, min_agent_interval_minutes, "
                    "max_users, last_threshold_alerted) "
                    "VALUES (:t, :tier, :conn, :agents, :queries, :gb, :intervalo, NULL, '{}')"
                ),
                valores,
            )
        elif str(existe[0]).strip().lower() in ("false", "0", "none", "f"):
            bind.execute(
                sa.text(
                    "UPDATE tenant_plan_limits SET tier = :tier, max_connections = :conn, "
                    "max_agents = :agents, max_queries_per_month = :queries, "
                    "max_storage_gb = :gb, min_agent_interval_minutes = :intervalo, "
                    "max_users = NULL WHERE tenant_id = :t"
                ),
                valores,
            )


def downgrade() -> None:
    bind = op.get_bind()
    if "tenant_plan_limits" not in sa.inspect(bind).get_table_names():
        return
    if bind.dialect.name == "postgresql":
        op.execute(
            "ALTER TABLE tenant_plan_limits DROP CONSTRAINT IF EXISTS tenant_plan_limits_tier_check"
        )
    for novo, antigo in (("core", "foundation"), ("plus", "scale")):
        bind.execute(
            sa.text("UPDATE tenant_plan_limits SET tier = :a WHERE tier = :n"),
            {"n": novo, "a": antigo},
        )
    if bind.dialect.name == "postgresql":
        op.execute(
            "ALTER TABLE tenant_plan_limits ADD CONSTRAINT tenant_plan_limits_tier_check "
            "CHECK (tier IN ('starter', 'foundation', 'scale', 'enterprise'))"
        )
    if (
        "tenant_registry" in sa.inspect(bind).get_table_names()
        and bind.dialect.name == "postgresql"
    ):
        op.execute(
            "ALTER TABLE tenant_registry DROP CONSTRAINT IF EXISTS tenant_registry_tier_check"
        )
        for novo, antigo in (("core", "foundation"), ("plus", "core"), ("enterprise", "strategic")):
            bind.execute(
                sa.text("UPDATE tenant_registry SET tier = :a WHERE tier = :n"),
                {"n": novo, "a": antigo},
            )
        op.execute(
            "ALTER TABLE tenant_registry ADD CONSTRAINT tenant_registry_tier_check "
            "CHECK (tier IN ('starter', 'foundation', 'core', 'advanced', 'strategic'))"
        )
    op.drop_column("tenant_plan_limits", "personalizado")
    op.drop_column("tenant_plan_limits", "min_agent_interval_minutes")
    op.drop_column("tenant_plan_limits", "max_connections")
