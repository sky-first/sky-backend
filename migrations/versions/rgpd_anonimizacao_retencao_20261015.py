"""RGPD: anonimização 30 dias após a remoção + retenção de 12 meses (15/10/2026).

Duas coisas, ambas para a política de privacidade nova ser verdade:

1. ``users.anonymized_at`` — quando a conta removida foi anonimizada. É o
   que torna a tarefa diária idempotente e o que impede restaurar uma conta
   depois de anonimizada.

2. Os gatilhos de ``audit_events`` deixam de bloquear TUDO. Continuam a
   recusar UPDATE e DELETE vindos de qualquer lado — excepto dentro de uma
   transacção que ligou explicitamente ``sky.rgpd_manutencao`` (só o
   ``src/services/rgpd_service.py`` o faz). E mesmo aí o UPDATE só pode
   mexer nos campos pessoais (``actor_email``, ``ip``, ``user_agent``,
   ``decision_reason``, ``metadata``): os campos que entram na cadeia de
   hashes ficam imutáveis, por isso a verificação da cadeia continua válida.
   O DELETE serve a retenção (linhas com mais de RETENCAO_AUDITORIA_DIAS).

Corre em todas as bases (plataforma e clientes). Idempotente: a coluna só se
cria se faltar, e as funções são ``CREATE OR REPLACE``.

Revision ID: rgpd_anonimizacao_retencao_20261015
Revises: ai_content_reports_20261015
Create Date: 2026-10-15
"""

import sqlalchemy as sa
from alembic import op

revision = "rgpd_anonimizacao_retencao_20261015"
down_revision = "ai_content_reports_20261015"
branch_labels = None
depends_on = None


_FUNCOES_COM_MANUTENCAO = """
CREATE OR REPLACE FUNCTION audit_prevent_update()
RETURNS TRIGGER AS $$
BEGIN
    IF current_setting('sky.rgpd_manutencao', true) = 'on'
       AND NEW.id = OLD.id
       AND NEW.occurred_at = OLD.occurred_at
       AND NEW.actor_kind = OLD.actor_kind
       AND NEW.actor_id IS NOT DISTINCT FROM OLD.actor_id
       AND NEW.action = OLD.action
       AND NEW.resource_kind IS NOT DISTINCT FROM OLD.resource_kind
       AND NEW.resource_id IS NOT DISTINCT FROM OLD.resource_id
       AND NEW.decision = OLD.decision
       AND NEW.prev_hash IS NOT DISTINCT FROM OLD.prev_hash
       AND NEW.this_hash = OLD.this_hash
    THEN
        RETURN NEW;
    END IF;
    RAISE EXCEPTION 'audit_events is append-only: UPDATE is not allowed';
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION audit_prevent_delete()
RETURNS TRIGGER AS $$
BEGIN
    IF current_setting('sky.rgpd_manutencao', true) = 'on' THEN
        RETURN OLD;
    END IF;
    RAISE EXCEPTION 'audit_events is append-only: DELETE is not allowed';
END;
$$ LANGUAGE plpgsql;
"""

_FUNCOES_ORIGINAIS = """
CREATE OR REPLACE FUNCTION audit_prevent_update()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'audit_events is append-only: UPDATE is not allowed';
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION audit_prevent_delete()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'audit_events is append-only: DELETE is not allowed';
END;
$$ LANGUAGE plpgsql;
"""


def _tem_coluna(tabela: str, coluna: str) -> bool:
    insp = sa.inspect(op.get_bind())
    if not insp.has_table(tabela):
        return True  # sem tabela não há onde acrescentar
    return coluna in {c["name"] for c in insp.get_columns(tabela)}


def upgrade() -> None:
    if not _tem_coluna("users", "anonymized_at"):
        op.add_column(
            "users",
            sa.Column("anonymized_at", sa.DateTime(timezone=True), nullable=True),
        )
    if op.get_bind().dialect.name == "postgresql":
        op.execute(_FUNCOES_COM_MANUTENCAO)


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(_FUNCOES_ORIGINAIS)
    insp = sa.inspect(op.get_bind())
    if insp.has_table("users") and "anonymized_at" in {
        c["name"] for c in insp.get_columns("users")
    }:
        op.drop_column("users", "anonymized_at")
