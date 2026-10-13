"""Prepara a base ``sky_world`` (fontes do sistema). Idempotente.

Corre como o utilizador mestre do RDS (o mesmo que cria a ``skydemo``), a
partir do Job ``world-bootstrap`` do sky-infra. Pode correr as vezes que se
quiser: cada passo verifica antes de fazer, e as passwords dos dois papéis
são acertadas com as do Secrets Manager a cada corrida (rodar = mudar o
segredo e voltar a correr o Job).

O que deixa feito:

- base ``sky_world`` sem nada para PUBLIC (nem CONNECT, nem TEMP) e com o
  esquema ``public`` fechado;
- ``world_loader`` (LOGIN) — dono do esquema ``mundo`` e das tabelas; só o
  CronJob do carregador o usa;
- ``world_admin`` (LOGIN, CREATEROLE, mais nada) — o backend usa-o para criar
  ``wsrc_*``/``wt_*`` e fazer GRANT/REVOKE. Recebe ``CONNECT`` e ``USAGE``
  com GRANT OPTION, e ``SELECT … WITH GRANT OPTION`` em todas as tabelas do
  ``mundo`` — as que existem e, por privilégios por omissão do
  ``world_loader``, as que o carregador vier a criar.

Uso::

    WORLD_BOOTSTRAP_DSN=postgresql://master:…@host:5432/postgres \\
    WORLD_LOADER_PASSWORD=… WORLD_ADMIN_PASSWORD=… \\
    python scripts/fontes_sistema/bootstrap_sky_world.py

Variáveis opcionais: ``WORLD_DB_NAME`` (sky_world), ``WORLD_SCHEMA`` (mundo),
``WORLD_LOADER_ROLE`` (world_loader), ``WORLD_ADMIN_ROLE`` (world_admin).
As passwords nunca são impressas.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from typing import Optional
from urllib.parse import urlsplit, urlunsplit

_IDENT = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")


def _ident(nome: str) -> str:
    if not _IDENT.match(nome or ""):
        raise SystemExit(f"identificador recusado: {nome!r}")
    return f'"{nome}"'


def _lit(pw: str) -> str:
    if not pw or len(pw) < 16:
        raise SystemExit("password vazia ou com menos de 16 caracteres")
    return "'" + pw.replace("'", "''") + "'"


def _dsn_para_base(dsn: str, base: str) -> str:
    p = urlsplit(dsn.replace("+asyncpg", "").replace("+psycopg2", ""))
    return urlunsplit((p.scheme, p.netloc, "/" + base, p.query, p.fragment))


def _papel(cur, nome: str, password: str, extra: str) -> None:
    cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (nome,))
    if cur.fetchone():
        cur.execute(f"ALTER ROLE {_ident(nome)} WITH LOGIN {extra} PASSWORD {_lit(password)}")
        print(f"  papel {nome}: password acertada")
    else:
        cur.execute(f"CREATE ROLE {_ident(nome)} WITH LOGIN {extra} PASSWORD {_lit(password)}")
        print(f"  papel {nome}: criado")


def bootstrap(
    dsn: str,
    loader_pw: str,
    admin_pw: str,
    *,
    base: str = "sky_world",
    esquema: str = "mundo",
    loader: str = "world_loader",
    admin: str = "world_admin",
) -> None:
    import psycopg2  # type: ignore[import-untyped]

    for n in (base, esquema, loader, admin):
        _ident(n)

    # ── 1. Base e papéis (ligado à base de manutenção) ───────────────────
    c = psycopg2.connect(dsn)
    c.autocommit = True
    with c.cursor() as cur:
        cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (base,))
        if not cur.fetchone():
            cur.execute(f"CREATE DATABASE {_ident(base)}")
            print(f"[1/4] base {base}: criada")
        else:
            print(f"[1/4] base {base}: já existe")
        _papel(cur, loader, loader_pw, "NOCREATEROLE NOCREATEDB")
        _papel(cur, admin, admin_pw, "CREATEROLE NOCREATEDB")
        # O mestre precisa de ser membro do loader para lhe mexer nos
        # privilégios por omissão (ALTER DEFAULT PRIVILEGES FOR ROLE).
        cur.execute(f"GRANT {_ident(loader)} TO CURRENT_USER")
    c.close()

    # ── 2. Dentro da base ────────────────────────────────────────────────
    c = psycopg2.connect(_dsn_para_base(dsn, base))
    c.autocommit = True
    with c.cursor() as cur:
        print("[2/4] fechar a base a PUBLIC")
        cur.execute(f"REVOKE ALL ON DATABASE {_ident(base)} FROM PUBLIC")
        cur.execute("REVOKE ALL ON SCHEMA public FROM PUBLIC")
        cur.execute(f"GRANT CONNECT, TEMPORARY ON DATABASE {_ident(base)} TO {_ident(loader)}")
        cur.execute(
            f"GRANT CONNECT ON DATABASE {_ident(base)} TO {_ident(admin)} WITH GRANT OPTION"
        )

        print(f"[3/4] esquema {esquema} do {loader}")
        cur.execute(f"CREATE SCHEMA IF NOT EXISTS {_ident(esquema)} AUTHORIZATION {_ident(loader)}")
        cur.execute(f"ALTER SCHEMA {_ident(esquema)} OWNER TO {_ident(loader)}")
        cur.execute(f"GRANT USAGE ON SCHEMA {_ident(esquema)} TO {_ident(admin)} WITH GRANT OPTION")

        print(f"[4/4] {admin} recebe SELECT com GRANT OPTION (actuais e futuras)")
        cur.execute(
            f"ALTER DEFAULT PRIVILEGES FOR ROLE {_ident(loader)} IN SCHEMA {_ident(esquema)} "
            f"GRANT SELECT ON TABLES TO {_ident(admin)} WITH GRANT OPTION"
        )
        # As que já existem (p.ex. carregadas antes do bootstrap): o mestre
        # é membro do loader, por isso concede em nome dele.
        cur.execute(f"SET ROLE {_ident(loader)}")
        cur.execute(
            f"GRANT SELECT ON ALL TABLES IN SCHEMA {_ident(esquema)} "
            f"TO {_ident(admin)} WITH GRANT OPTION"
        )
        cur.execute("RESET ROLE")
    c.close()
    print("Feito.")


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dsn", default=os.environ.get("WORLD_BOOTSTRAP_DSN"))
    args = ap.parse_args(argv)
    if not args.dsn:
        print("Falta WORLD_BOOTSTRAP_DSN (ou --dsn).", file=sys.stderr)
        return 2
    loader_pw = os.environ.get("WORLD_LOADER_PASSWORD") or ""
    admin_pw = os.environ.get("WORLD_ADMIN_PASSWORD") or ""
    bootstrap(
        args.dsn,
        loader_pw,
        admin_pw,
        base=os.environ.get("WORLD_DB_NAME", "sky_world"),
        esquema=os.environ.get("WORLD_SCHEMA", "mundo"),
        loader=os.environ.get("WORLD_LOADER_ROLE", "world_loader"),
        admin=os.environ.get("WORLD_ADMIN_ROLE", "world_admin"),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
