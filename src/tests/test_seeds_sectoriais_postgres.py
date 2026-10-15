# -*- coding: utf-8 -*-
"""Os seeds dos três projectos sectoriais contra um Postgres A SÉRIO.

Carrega `seed_food.sql`, `seed_transport.sql` e `seed_restaurant.sql`
numa base nova — duas vezes, porque o Job de produção volta a correr a
cada 24 h e o segundo carregamento tem de dar o mesmo que o primeiro —
e depois verifica três coisas:

  1. **as invariantes** de `scripts/demo/verificar_sectores.py`: nada
     empatado onde a bateria de 14/10/2026 apanhou empates, coerência
     entre tabelas, nada no futuro, e as histórias de cada demonstração
     (as viaturas velhas, as rotas 4 e 11, as lojas 3 e 8…);
  2. **cada widget, pergunta semeada e métrica** dos três sectores corre
     e devolve linhas — o semeador recusa gravar um widget vazio, e uma
     métrica que rebenta é uma métrica que a IA lê e não consegue usar;
  3. **a resposta das cinco perguntas** monta-se sem rebentar com os
     dados novos.

Precisa de ``WORLD_TEST_PG_DSN`` (o mesmo Postgres que
`test_fontes_sistema_postgres.py` usa). Sem ela, salta — na CI tem de
existir.
"""
from __future__ import annotations

import os
import secrets
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import pytest

DSN = os.environ.get("WORLD_TEST_PG_DSN")
if not DSN and os.environ.get("GITHUB_ACTIONS") == "true":
    raise RuntimeError("WORLD_TEST_PG_DSN em falta na CI (serviço postgres do ci-pr-gate)")
pytestmark = [
    pytest.mark.skipif(not DSN, reason="sem WORLD_TEST_PG_DSN (Postgres real)"),
    # Os seeds geram ~200 mil linhas; o tecto de 120 s da CI é por teste
    # e a fixture conta para o primeiro.
    pytest.mark.timeout(900),
]

RAIZ = Path(__file__).resolve().parents[2]
SEEDS = ["seed_food.sql", "seed_transport.sql", "seed_restaurant.sql"]


def _dsn(base: str) -> str:
    p = urlsplit(DSN)
    return urlunsplit((p.scheme.replace("+asyncpg", ""), p.netloc, "/" + base, p.query, ""))


def _carregar(dsn: str) -> None:
    import psycopg2

    for nome in SEEDS:
        sql = (RAIZ / "scripts" / "demo" / nome).read_text(encoding="utf-8")
        # Uma ligação por ficheiro, como o `psql -f` do Job: as funções em
        # `pg_temp` e as tabelas temporárias morrem com ela.
        conn = psycopg2.connect(dsn)
        conn.autocommit = True  # o ficheiro traz o seu BEGIN/COMMIT
        try:
            with conn.cursor() as cur:
                cur.execute(sql)
        finally:
            conn.close()


@pytest.fixture(scope="module")
def base():
    import psycopg2

    nome = f"seeds_t{secrets.token_hex(3)}"
    admin = psycopg2.connect(DSN)
    admin.autocommit = True
    with admin.cursor() as cur:
        cur.execute(f"CREATE DATABASE {nome}")
    try:
        dsn = _dsn(nome)
        _carregar(dsn)
        primeira = _contagens(dsn)
        _carregar(dsn)  # re-executável: o Job corre todos os dias
        segunda = _contagens(dsn)
        yield dsn, primeira, segunda
    finally:
        with admin.cursor() as cur:
            cur.execute(f"DROP DATABASE IF EXISTS {nome} WITH (FORCE)")
        admin.close()


def _contagens(dsn: str) -> dict:
    import psycopg2

    tabelas = [
        "assortment.products",
        "warehouse.lots",
        "warehouse.stock",
        "trade.customers",
        "trade.orders",
        "trade.order_lines",
        "fleet.vehicles",
        "fleet.maintenance_jobs",
        "ops.trips",
        "freight.shipments",
        "restaurant.staff_shifts",
        "service.orders",
        "service.order_items",
        "kitchen.waste",
    ]
    with psycopg2.connect(dsn) as conn, conn.cursor() as cur:
        out = {}
        for t in tabelas:
            cur.execute(f"SELECT COUNT(*) FROM {t}")
            out[t] = cur.fetchone()[0]
        cur.execute("SELECT ROUND(SUM(quantity * unit_price), 2) FROM trade.order_lines")
        out["facturado"] = cur.fetchone()[0]
        return out


def _cursor(dsn: str):
    import psycopg2

    conn = psycopg2.connect(dsn)
    conn.set_session(readonly=True, autocommit=True)
    return conn


def _invariantes():
    import importlib.util

    caminho = RAIZ / "scripts" / "demo" / "verificar_sectores.py"
    spec = importlib.util.spec_from_file_location("verificar_sectores", caminho)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _sectores():
    from scripts.demo_sectorial import alimentacion, restauracion, transportes

    return [alimentacion.SECTOR, transportes.SECTOR, restauracion.SECTOR]


def _consultas():
    for s in _sectores():
        for pg in s.paginas:
            for w in pg.widgets:
                yield f"{s.chave}/widget/{pg.nome}/{w.titulo}", w.sql, w
        for pq in s.perguntas:
            yield f"{s.chave}/pergunta/{pq.texto}", pq.sql, pq
        for m in s.metricas:
            yield f"{s.chave}/metrica/{m.nome}", m.formula, None


# ── Um teste só, de propósito ───────────────────────────────────────
#
# A CI corre com `pytest-xdist -n auto`, e uma fixture de módulo é
# construída UMA VEZ POR WORKER. Com os casos parametrizados, quatro
# workers carregavam os seeds oito vezes no mesmo Postgres. Um teste só
# carrega duas (a segunda prova que é re-executável) e junta todas as
# falhas numa mensagem — que é o que se quer ler quando falha.


def test_o_segundo_carregamento_da_o_mesmo_que_o_primeiro(base):
    _, primeira, segunda = base
    assert primeira == segunda
    assert primeira["service.orders"] > 50_000
    assert primeira["ops.trips"] > 3_000


def test_invariantes_e_consultas_dos_tres_sectores(base):
    from scripts.demo_sectorial.motor import _converter

    dsn, _, _ = base
    verificar = _invariantes()
    falhas: list[str] = []
    conn = _cursor(dsn)
    try:
        with conn.cursor() as cur:
            for nome, passou, linhas in verificar.invariantes(cur):
                if not passou:
                    falhas.append(f"✗ invariante «{nome}»: {linhas}")

            for onde, sql, peca in _consultas():
                try:
                    cur.execute(sql)
                except Exception as e:  # noqa: BLE001
                    falhas.append(f"✗ {onde}: rebentou — {e}")
                    continue
                cols = [c[0] for c in cur.description]
                linhas = [{k: _converter(v) for k, v in zip(cols, r)} for r in cur.fetchall()]
                if not linhas:
                    falhas.append(f"✗ {onde}: sem linhas — o semeador recusa um widget vazio")
                    continue
                # Um nulo num KPI ou numa métrica aparece como «—» no ecrã.
                if all(v is None for v in linhas[0].values()):
                    falhas.append(f"✗ {onde}: só nulos")
                    continue
                if peca is None:
                    continue
                try:
                    if hasattr(peca, "resposta"):
                        texto = peca.resposta(linhas)
                        if not texto or "None" in texto:
                            falhas.append(f"✗ {onde}: resposta {texto[:160]!r}")
                    else:
                        dados = peca.dados(linhas)
                        if "None" in str(dados.get("content", "")):
                            falhas.append(f"✗ {onde}: {dados}")
                except Exception as e:  # noqa: BLE001
                    falhas.append(f"✗ {onde}: a montar a peça — {e!r}")
    finally:
        conn.close()
    assert not falhas, "\n".join(falhas)
