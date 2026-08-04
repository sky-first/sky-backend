"""As migrações do conteúdo da demo — BE-12.

O resto da suite provisiona o esquema com ``Base.metadata.create_all``,
o que significa que **nenhum teste executava as migrações**. São dois
caminhos diferentes a produzir o mesmo esquema, e a divergência entre
eles só apareceria em produção — que é onde as migrações correm e o
``create_all`` não.

Este ficheiro corre as migrações a sério. Ainda em SQLite, portanto os
ramos específicos do Postgres (pgvector, índices parciais nativos) não
ficam cobertos; o que fica coberto é que as migrações executam, que as
tabelas saem com as colunas certas, e que o índice parcial impõe o que
diz impor. Apanhou já uma coluna que existia por um caminho e não pelo
outro.
"""

from __future__ import annotations

import importlib.util
import uuid
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS = ("demo_content_20260803", "demo_leads_20260803")


def _load(name: str):
    spec = importlib.util.spec_from_file_location(
        name, ROOT / "migrations" / "versions" / f"{name}.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


@pytest.fixture()
def migrated():
    """Base em memória com as migrações da demo aplicadas."""
    engine = create_engine("sqlite:///:memory:")
    conn = engine.connect()
    ctx = MigrationContext.configure(conn)
    with Operations.context(ctx):
        for name in MIGRATIONS:
            _load(name).upgrade()
    try:
        yield conn
    finally:
        conn.close()
        engine.dispose()


def _insert_dataset(conn, *, vertical, is_default, locale="en"):
    conn.execute(
        text(
            "INSERT INTO demo_datasets "
            "(id, vertical, name, is_default, locale, created_at, updated_at) "
            "VALUES (:id, :v, :n, :d, :l, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        ),
        {
            "id": str(uuid.uuid4()),
            "v": vertical,
            "n": f"Demo {vertical}",
            "d": 1 if is_default else 0,
            "l": locale,
        },
    )


def test_migracoes_executam(migrated):
    tables = {t for t in inspect(migrated).get_table_names() if t.startswith("demo_")}

    assert tables == {"demo_datasets", "demo_insights", "demo_qas", "demo_leads"}


def test_embedding_existe_em_qualquer_dialecto(migrated):
    """O modelo declara `embedding`; se a migração não a criasse,
    qualquer SELECT sobre demo_qas rebentava. Já divergiu uma vez entre
    a migração e o create_all."""
    cols = {c["name"] for c in inspect(migrated).get_columns("demo_qas")}

    assert "embedding" in cols


def test_duas_verticais_partilham_o_mesmo_idioma(migrated):
    """O índice parcial só pode ser único entre os defaults. Sem o
    predicado no dialecto certo torna-se único sobre `locale` inteiro e
    proíbe semear a segunda vertical — o bug que motivou o teste."""
    _insert_dataset(migrated, vertical="saas", is_default=False)
    _insert_dataset(migrated, vertical="distribution", is_default=False)

    count = migrated.execute(text("SELECT COUNT(*) FROM demo_datasets")).scalar()
    assert count == 2


def test_so_um_default_por_idioma(migrated):
    """Dois defaults tornariam a entrada da demo não-determinista — quem
    carrega em 'Saltar' iria parar a sítios diferentes conforme o plano
    de execução."""
    _insert_dataset(migrated, vertical="default", is_default=True)

    with pytest.raises(IntegrityError):
        _insert_dataset(migrated, vertical="saas", is_default=True)


def test_default_por_idioma_e_independente(migrated):
    """Um default em inglês não pode impedir um default em português."""
    _insert_dataset(migrated, vertical="default", is_default=True, locale="en")
    _insert_dataset(migrated, vertical="default", is_default=True, locale="pt-PT")

    count = migrated.execute(text("SELECT COUNT(*) FROM demo_datasets WHERE is_default")).scalar()
    assert count == 2


def test_lead_e_unico_por_email(migrated):
    """A idempotência do serviço assenta nesta restrição."""
    for _ in range(2):
        stmt = text(
            "INSERT INTO demo_leads (id, email, questions_asked, created_at, updated_at) "
            "VALUES (:id, 'jane@acme.com', '[]', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        )
        if _ == 0:
            migrated.execute(stmt, {"id": str(uuid.uuid4())})
        else:
            with pytest.raises(IntegrityError):
                migrated.execute(stmt, {"id": str(uuid.uuid4())})
