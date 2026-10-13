"""Fontes do sistema — catálogo, activação por cliente e a ligação gerida (13/10/2026).

Ver ``docs/contrato-fontes-do-sistema.md``.

1. ``fontes_sistema`` e ``fontes_sistema_cliente`` — só onde há
   ``tenant_registry`` (a base da plataforma; nas dos clientes a tabela do
   registo também existe, e aí ficam vazias: ninguém as lê).
2. ``data_connections.sistema`` (todas as bases) + índice parcial único:
   no máximo UMA ligação do sistema viva por cliente.
3. ``internal_console_audit``: cinco acções novas no CHECK.
4. Catálogo semeado com as fontes de tipo A de licença limpa, mais as de
   tipo B (TomTom) em ``rascunho`` — prontas para a fase 2, sem ligar nada.

Revision ID: fontes_sistema_20261013
Revises: planos_uma_tabela_20261010
Create Date: 2026-10-13
"""

from __future__ import annotations


import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "fontes_sistema_20261013"
down_revision = "planos_uma_tabela_20261010"
branch_labels = None
depends_on = None

_AUDIT_ANTIGAS = (
    "view_tenant",
    "view_audit",
    "view_dashboard",
    "create_tenant",
    "update_tenant",
    "suspend_tenant",
    "resume_tenant",
    "destroy_tenant",
    "change_tier",
    "update_capacity",
    "update_db_config",
    "test_db_config",
    "grant_role",
    "revoke_role",
)
_AUDIT_NOVAS = _AUDIT_ANTIGAS + (
    "enable_system_source",
    "disable_system_source",
    "edit_system_source",
    "retire_system_source",
    "reconcile_system_sources",
)

_TODOS = ["starter", "core", "plus", "enterprise"]

# Copiado de propósito (uma migração não muda quando o código muda).
# Licenças: docs/DADOS_EXTERNOS_COMERCIAL_2026-10.md e
# scripts/dados_publicos/mundo/README.md. `rotas_referencia` e
# `gasolineras_rota` NÃO entram em nenhuma fonte enquanto os termos de
# armazenamento da TomTom não estiverem confirmados (S8, L2, L8).
_CATALOGO = [
    dict(
        id="combustivel_es",
        nome={
            "pt": "Combustível Espanha (MITECO)",
            "es": "Carburantes España (MITECO)",
            "en": "Fuel prices Spain (MITECO)",
        },
        descricao={
            "pt": "Preço actual de cada posto em Espanha e histórico diário do gasóleo por província.",
            "es": "Precio actual de cada estación en España e histórico diario del gasóleo por provincia.",
            "en": "Current price at every Spanish station and daily diesel history by province.",
        },
        estado="ativa",
        tabelas=["gasolineras_precio", "gasoleo_historico_diario"],
        nome_carregador=["gasolineras", "gasoleo_historico"],
        licenca="MITECO — reutilização (Lei 37/2007, RD 1495/2011)",
        atribuicao={"pt": "Fuente: Ministerio para la Transición Ecológica"},
        uso_comercial=True,
        cadencia_min=30,
    ),
    dict(
        id="combustivel_ue",
        nome={
            "pt": "Combustível UE (Weekly Oil Bulletin)",
            "es": "Carburantes UE (Weekly Oil Bulletin)",
            "en": "Fuel prices EU (Weekly Oil Bulletin)",
        },
        descricao={
            "pt": "Médias nacionais semanais ES, PT e UE com impostos.",
            "es": "Medias nacionales semanales ES, PT y UE con impuestos.",
            "en": "Weekly national averages ES, PT and EU incl. taxes.",
        },
        estado="ativa",
        tabelas=["gasoleo_ue_semanal"],
        nome_carregador=["gasoleo_ue"],
        licenca="Comissão Europeia — reutilização com citação (Decisão 2011/833/UE)",
        atribuicao={"pt": "Fonte: Comissão Europeia, Weekly Oil Bulletin"},
        uso_comercial=True,
        cadencia_min=10080,
    ),
    dict(
        id="trafego_dgt",
        nome={
            "pt": "Trânsito DGT (DATEX II)",
            "es": "Tráfico DGT (DATEX II)",
            "en": "Traffic DGT (DATEX II)",
        },
        descricao={
            "pt": "Incidências de trânsito activas na rede da DGT.",
            "es": "Incidencias de tráfico activas en la red de la DGT.",
            "en": "Active traffic incidents on the DGT network.",
        },
        # ⚠ L3: confirmar com o NAP que o CC BY prevalece sobre o aviso legal.
        estado="rascunho",
        tabelas=["incidencias_trafico"],
        nome_carregador=["incidencias"],
        licenca="DGT NAP — CC BY (Reg. UE 886/2013) — por confirmar",
        atribuicao={"pt": "Fuente: DGT"},
        uso_comercial=True,
        cadencia_min=5,
    ),
    dict(
        id="feriados_es_pt",
        nome={
            "pt": "Feriados Espanha e Portugal",
            "es": "Festivos España y Portugal",
            "en": "Public holidays Spain and Portugal",
        },
        descricao={
            "pt": "Feriados nacionais e regionais ES (BOE) e nacionais PT (DRE).",
            "es": "Festivos nacionales y autonómicos ES (BOE) y nacionales PT (DRE).",
            "en": "National and regional holidays ES (BOE) and national PT (DRE).",
        },
        estado="ativa",
        tabelas=["festivos"],
        nome_carregador=["festivos"],
        licenca="BOE — Licencia tipo; DRE — legislação pública",
        atribuicao={
            "pt": "Basado en datos de la Agencia Estatal Boletín Oficial del Estado (boe.es); "
            "Fonte: Diário da República"
        },
        uso_comercial=True,
        cadencia_min=43200,
    ),
    dict(
        id="cambio_bce",
        nome={
            "pt": "Câmbios BCE",
            "es": "Tipos de cambio BCE",
            "en": "ECB exchange rates",
        },
        descricao={
            "pt": "Câmbios de referência do BCE, últimos 90 dias.",
            "es": "Tipos de referencia del BCE, últimos 90 días.",
            "en": "ECB reference rates, last 90 days.",
        },
        estado="ativa",
        tabelas=["cambio_eur"],
        nome_carregador=["cambio"],
        licenca="BCE — reprodução com citação; Frankfurter «free for commercial use»",
        atribuicao={"pt": "Fuente: BCE (tipos de referencia, gratuitos en ecb.europa.eu)"},
        uso_comercial=True,
        cadencia_min=1440,
    ),
    dict(
        id="tempo_aemet",
        nome={
            "pt": "Previsão do tempo (AEMET)",
            "es": "Previsión meteorológica (AEMET)",
            "en": "Weather forecast (AEMET)",
        },
        descricao={
            "pt": "Previsão diária a 7 dias nas cidades das rotas.",
            "es": "Previsión diaria a 7 días en las ciudades de las rutas.",
            "en": "7-day daily forecast in route cities.",
        },
        # Só corre com AEMET_API_KEY; activar quando o carregador a tiver.
        estado="rascunho",
        tabelas=["tempo_cidades"],
        nome_carregador=["tempo"],
        licenca="AEMET OpenData; Open-Meteo com subscrição (CC BY 4.0)",
        atribuicao={"pt": "Fuente: AEMET · Weather data by Open-Meteo.com (CC BY 4.0)"},
        uso_comercial=True,
        cadencia_min=360,
    ),
    dict(
        id="portagens_es_pt",
        nome={
            "pt": "Portagens de referência",
            "es": "Peajes de referencia",
            "en": "Reference tolls",
        },
        descricao={
            "pt": "Portagens 2026 nos corredores ES/PT (tabela manual).",
            "es": "Peajes 2026 en los corredores ES/PT (tabla manual).",
            "en": "2026 tolls on ES/PT corridors (manual table).",
        },
        estado="ativa",
        tabelas=["portagens"],
        nome_carregador=["portagens"],
        licenca="Tarifas públicas (BOE / concessionárias); compilação própria",
        atribuicao={"pt": "Fontes por linha (BOE, Brisa, administracion.gob.es)"},
        uso_comercial=True,
        cadencia_min=525600,
    ),
    dict(
        id="restricoes_dgt",
        nome={
            "pt": "Restrições a pesados (DGT)",
            "es": "Restricciones a pesados (DGT)",
            "en": "Heavy vehicle restrictions (DGT)",
        },
        descricao={
            "pt": "Restrições DGT 2026 a mais de 7.500 kg (Anexo II).",
            "es": "Restricciones DGT 2026 a más de 7.500 kg (Anexo II).",
            "en": "DGT 2026 restrictions for vehicles over 7,500 kg (Annex II).",
        },
        estado="ativa",
        tabelas=["restricoes_pesados"],
        nome_carregador=["restricoes"],
        licenca="BOE — Licencia tipo",
        atribuicao={"pt": "Basado en datos de la DGT / Agencia Estatal Boletín Oficial del Estado"},
        uso_comercial=True,
        cadencia_min=525600,
    ),
    # ── Tipo B: fase 2. Em rascunho, sem tabelas; as colunas ficam prontas.
    dict(
        id="tomtom_rotas",
        tipo="B",
        nome={
            "pt": "Rotas de camião (TomTom)",
            "es": "Rutas de camión (TomTom)",
            "en": "Truck routing (TomTom)",
        },
        estado="rascunho",
        ferramentas=["rota_camiao"],
        licenca="TomTom Routing — termos de cache por confirmar",
        atribuicao={"pt": "Routing © TomTom"},
        uso_comercial=True,
        modelo_custo={"tipo": "por_pedido", "gratis_mes": 20000, "tecto_global_mes": 18000},
        quota_omissao={"starter": 0, "core": 300, "plus": 1500, "enterprise": None},
        planos_permitidos=["core", "plus", "enterprise"],
    ),
    dict(
        id="tomtom_geocod",
        tipo="B",
        nome={
            "pt": "Geocodificação (TomTom)",
            "es": "Geocodificación (TomTom)",
            "en": "Geocoding (TomTom)",
        },
        estado="rascunho",
        ferramentas=["geocodificar"],
        licenca="TomTom Search — termos de cache por confirmar",
        atribuicao={"pt": "© TomTom"},
        uso_comercial=True,
        modelo_custo={"tipo": "por_pedido", "gratis_mes": 20000, "tecto_global_mes": 18000},
        quota_omissao={"starter": 0, "core": 300, "plus": 1500, "enterprise": None},
        planos_permitidos=["core", "plus", "enterprise"],
    ),
]


def _json_type(bind):
    return postgresql.JSONB() if bind.dialect.name == "postgresql" else sa.JSON()


def upgrade() -> None:
    bind = op.get_bind()
    tabelas = set(sa.inspect(bind).get_table_names())
    J = _json_type(bind)

    # ── 2. A ligação do sistema, em todas as bases ──────────────────────
    if "data_connections" in tabelas:
        colunas = {c["name"] for c in sa.inspect(bind).get_columns("data_connections")}
        if "sistema" not in colunas:
            op.add_column(
                "data_connections",
                sa.Column("sistema", sa.Boolean(), nullable=False, server_default="false"),
            )
        if bind.dialect.name == "postgresql":
            op.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_data_connections_uma_do_sistema "
                "ON data_connections ((sistema)) WHERE sistema AND deleted_at IS NULL"
            )

    # ── 3. Auditoria da Consola ─────────────────────────────────────────
    if bind.dialect.name == "postgresql" and "internal_console_audit" in tabelas:
        op.execute(
            "ALTER TABLE internal_console_audit "
            "DROP CONSTRAINT IF EXISTS internal_console_audit_action_check"
        )
        valores = ", ".join(f"'{v}'" for v in _AUDIT_NOVAS)
        op.execute(
            "ALTER TABLE internal_console_audit "
            "ADD CONSTRAINT internal_console_audit_action_check "
            f"CHECK (action IN ({valores}))"
        )

    # ── 1. Catálogo + activação: só onde há registo de clientes ────────
    if "tenant_registry" not in tabelas:
        return
    if "fontes_sistema" not in tabelas:
        op.create_table(
            "fontes_sistema",
            sa.Column("id", sa.String(64), primary_key=True),
            sa.Column("nome", J, nullable=False),
            sa.Column("descricao", J, nullable=True),
            sa.Column("tipo", sa.String(1), nullable=False, server_default="A"),
            sa.Column("estado", sa.String(20), nullable=False, server_default="rascunho"),
            sa.Column("tabelas", J, nullable=False, server_default="[]"),
            sa.Column("nome_carregador", J, nullable=False, server_default="[]"),
            sa.Column("ferramentas", J, nullable=False, server_default="[]"),
            sa.Column("licenca", sa.Text(), nullable=True),
            sa.Column("atribuicao", J, nullable=True),
            sa.Column("uso_comercial", sa.Boolean(), nullable=False, server_default="false"),
            sa.Column("cadencia_min", sa.Integer(), nullable=True),
            sa.Column("modelo_custo", J, nullable=True),
            sa.Column(
                "planos_permitidos",
                J,
                nullable=False,
                server_default='["starter", "core", "plus", "enterprise"]',
            ),
            sa.Column("conta_como_fonte", sa.Boolean(), nullable=False, server_default="false"),
            sa.Column("quota_omissao", J, nullable=True),
            sa.Column("versao", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("criado_por", sa.String(255), nullable=True),
            sa.Column(
                "criado_em",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column(
                "actualizado_em",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.CheckConstraint("tipo IN ('A', 'B')", name="fontes_sistema_tipo_check"),
            sa.CheckConstraint(
                "estado IN ('rascunho', 'ativa', 'retirada')", name="fontes_sistema_estado_check"
            ),
            sa.CheckConstraint(
                "estado <> 'ativa' OR uso_comercial", name="fontes_sistema_ativa_exige_comercial"
            ),
        )
    if "fontes_sistema_cliente" not in tabelas:
        op.create_table(
            "fontes_sistema_cliente",
            sa.Column(
                "tenant_id",
                postgresql.UUID(as_uuid=True) if bind.dialect.name == "postgresql" else sa.CHAR(32),
                sa.ForeignKey("tenant_registry.id", ondelete="CASCADE"),
                primary_key=True,
            ),
            sa.Column(
                "fonte_id",
                sa.String(64),
                sa.ForeignKey("fontes_sistema.id", ondelete="RESTRICT"),
                primary_key=True,
            ),
            sa.Column("ativa", sa.Boolean(), nullable=False, server_default="false"),
            sa.Column("estado", sa.String(20), nullable=False, server_default="a_preparar"),
            sa.Column("erro", J, nullable=True),
            sa.Column("quota_mes", sa.Integer(), nullable=True),
            sa.Column(
                "pedido_id",
                postgresql.UUID(as_uuid=True) if bind.dialect.name == "postgresql" else sa.CHAR(32),
                nullable=False,
            ),
            sa.Column("ativada_por", sa.String(255), nullable=True),
            sa.Column("ativada_em", sa.DateTime(timezone=True), nullable=True),
            sa.Column("desativada_por", sa.String(255), nullable=True),
            sa.Column("desativada_em", sa.DateTime(timezone=True), nullable=True),
            sa.Column("pronta_em", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "actualizado_em",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.CheckConstraint(
                "estado IN ('a_preparar', 'pronta', 'erro', 'a_desligar', 'desligada')",
                name="fontes_sistema_cliente_estado_check",
            ),
        )

    # ── 4. Sementeira do catálogo (idempotente: não pisa edições) ──────
    for f in _CATALOGO:
        existe = bind.execute(
            sa.text("SELECT 1 FROM fontes_sistema WHERE id = :id"), {"id": f["id"]}
        ).first()
        if existe:
            continue
        bind.execute(
            sa.text(
                "INSERT INTO fontes_sistema (id, nome, descricao, tipo, estado, tabelas, "
                "nome_carregador, ferramentas, licenca, atribuicao, uso_comercial, "
                "cadencia_min, modelo_custo, planos_permitidos, conta_como_fonte, "
                "quota_omissao, versao, criado_por) VALUES (:id, :nome, :descricao, :tipo, "
                ":estado, :tabelas, :nome_carregador, :ferramentas, :licenca, :atribuicao, "
                ":uso_comercial, :cadencia_min, :modelo_custo, :planos_permitidos, false, "
                ":quota_omissao, 1, 'migracao')"
            ).bindparams(
                sa.bindparam("nome", type_=J),
                sa.bindparam("descricao", type_=J),
                sa.bindparam("tabelas", type_=J),
                sa.bindparam("nome_carregador", type_=J),
                sa.bindparam("ferramentas", type_=J),
                sa.bindparam("atribuicao", type_=J),
                sa.bindparam("modelo_custo", type_=J),
                sa.bindparam("planos_permitidos", type_=J),
                sa.bindparam("quota_omissao", type_=J),
            ),
            dict(
                id=f["id"],
                nome=f["nome"],
                descricao=f.get("descricao"),
                tipo=f.get("tipo", "A"),
                estado=f["estado"],
                tabelas=f.get("tabelas", []),
                nome_carregador=f.get("nome_carregador", []),
                ferramentas=f.get("ferramentas", []),
                licenca=f.get("licenca"),
                atribuicao=f.get("atribuicao"),
                uso_comercial=f.get("uso_comercial", False),
                cadencia_min=f.get("cadencia_min"),
                modelo_custo=f.get("modelo_custo"),
                planos_permitidos=f.get("planos_permitidos", _TODOS),
                quota_omissao=f.get("quota_omissao"),
            ),
        )


def downgrade() -> None:
    bind = op.get_bind()
    tabelas = set(sa.inspect(bind).get_table_names())
    if "fontes_sistema_cliente" in tabelas:
        op.drop_table("fontes_sistema_cliente")
    if "fontes_sistema" in tabelas:
        op.drop_table("fontes_sistema")
    if bind.dialect.name == "postgresql":
        op.execute("DROP INDEX IF EXISTS uq_data_connections_uma_do_sistema")
        if "internal_console_audit" in tabelas:
            op.execute(
                "DELETE FROM internal_console_audit WHERE action IN ("
                + ", ".join(f"'{v}'" for v in _AUDIT_NOVAS[len(_AUDIT_ANTIGAS) :])
                + ")"
            )
            op.execute(
                "ALTER TABLE internal_console_audit "
                "DROP CONSTRAINT IF EXISTS internal_console_audit_action_check"
            )
            op.execute(
                "ALTER TABLE internal_console_audit "
                "ADD CONSTRAINT internal_console_audit_action_check "
                f"CHECK (action IN ({', '.join(repr(v) for v in _AUDIT_ANTIGAS)}))"
            )
    if "data_connections" in tabelas:
        colunas = {c["name"] for c in sa.inspect(bind).get_columns("data_connections")}
        if "sistema" in colunas:
            op.drop_column("data_connections", "sistema")
