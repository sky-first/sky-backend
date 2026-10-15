# TEMPORÁRIO — diagnóstico na CI (antes/depois). Sai antes do merge.
import os, secrets, time
from pathlib import Path
import pytest

DSN = os.environ.get("WORLD_TEST_PG_DSN")
pytestmark = [pytest.mark.skipif(not DSN, reason="sem Postgres"), pytest.mark.timeout(1200)]
RAIZ = Path(__file__).resolve().parents[2]


def _verificar():
    import importlib.util
    spec = importlib.util.spec_from_file_location("v", RAIZ / "scripts/demo/verificar_sectores.py")
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m


def _construir(pasta):
    import psycopg2
    from urllib.parse import urlsplit, urlunsplit
    nome = f"diag_{secrets.token_hex(3)}"
    a = psycopg2.connect(DSN); a.autocommit = True
    a.cursor().execute(f"CREATE DATABASE {nome}")
    p = urlsplit(DSN)
    dsn = urlunsplit((p.scheme, p.netloc, "/" + nome, p.query, ""))
    tempos = []
    for f in ["seed_food.sql", "seed_transport.sql", "seed_restaurant.sql"]:
        t0 = time.time()
        c = psycopg2.connect(dsn); c.autocommit = True
        c.cursor().execute((pasta / f).read_text(encoding="utf-8")); c.close()
        tempos.append(f"{f}={time.time()-t0:.1f}s")
    return a, nome, dsn, tempos


def test_diagnostico():
    import psycopg2
    v = _verificar()
    out = []
    for rotulo, pasta in [("ANTES", RAIZ / "src/tests/_seeds_antigos"), ("DEPOIS", RAIZ / "scripts/demo")]:
        a, nome, dsn, tempos = _construir(pasta)
        try:
            c = psycopg2.connect(dsn); cur = c.cursor()
            out.append(f"\n\n######## {rotulo}  ({', '.join(tempos)})")
            out.append(v.relatorio(cur))
            if rotulo == "DEPOIS":
                for n, ok, linhas in v.invariantes(cur):
                    out.append(f"{'OK ' if ok else 'XX '} {n} -> {linhas if not ok else ''}")
            c.close()
        finally:
            a.cursor().execute(f"DROP DATABASE IF EXISTS {nome} WITH (FORCE)"); a.close()
    pytest.fail("\n".join(out))
